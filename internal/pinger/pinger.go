package pinger

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"github.com/go-ping/ping"
	"github.com/rs/zerolog/log"
	"os/exec"
	"time"
)

type Pinger interface {
	Start()
	Stop()
	GetResultData() map[string][]byte
}

type pinger struct {
	isSender bool

	icmpPinger *ping.Pinger
	icmpData   ICMPPingData

	irttProcess *exec.Cmd
	irttResults []byte
	irttExited  chan struct{}

	stopping bool
}

func NewPinger(targetAddress string, enableICMP bool, enableUDP bool, isSender bool, interval time.Duration, irttDuration time.Duration) (Pinger, error) {
	p := pinger{
		isSender:   isSender,
		irttExited: make(chan struct{}),
		stopping:   false,
	}

	if enableICMP && isSender {
		pingr, err := ping.NewPinger(targetAddress)
		if err != nil {
			return nil, err
		}
		pingr.SetPrivileged(true)

		p.icmpPinger = pingr

		pingr.OnRecv = func(pkt *ping.Packet) {
			p.icmpData.Pings = append(p.icmpData.Pings, Ping{
				ReplyRecvTime: time.Now(),
				Rtt:           pkt.Rtt,
				Seq:           pkt.Seq,
				Ttl:           pkt.Ttl,
			})
		}
		pingr.Interval = interval
		pingr.RecordRtts = false
	}

	if enableUDP {

		if isSender {
			irttArgs := []string{"client", "-i", fmt.Sprintf("%dms", interval.Milliseconds()), "-d", fmt.Sprintf("%dms", irttDuration.Milliseconds()), "-o", "-", targetAddress}
			p.irttProcess = exec.Command("bin/irtt", irttArgs...)
			go p.startIrttStdoutReader()
		} else {
			p.irttProcess = exec.Command("bin/irtt", "server")
			go p.startIrttStdoutReader()
			log.Info().Msg("Starting IRTT server...")
			err := p.irttProcess.Start()
			if err != nil {
				return nil, err
			}
		}
	}

	return &p, nil
}

func (p *pinger) Start() {
	if p.icmpPinger != nil {
		log.Info().Msgf("Starting ICMP pinger...")
		go func() {
			err := p.icmpPinger.Run()
			if err != nil {
				log.Fatal().Err(err).Msg("Failed to start pinger")
			}
		}()
	}
	if p.irttProcess != nil {
		if p.isSender {
			log.Info().Msgf("Starting IRTT client...")
			err := p.irttProcess.Start()
			if err != nil {
				log.Fatal().Err(err).Msg("Failed to start IRTT client")
				return
			}
		}
	}

}

func (p *pinger) Stop() {
	p.stopping = true
	if p.icmpPinger != nil {
		log.Info().Msgf("Stopping ICMP pinger...")
		p.icmpPinger.Stop()
		log.Info().Msgf("Stopped ICMP pinger")
	}
	if p.irttProcess != nil {
		if p.isSender {
			log.Info().Msgf("Waiting for IRTT client to exit...")
		} else {
			log.Info().Msgf("Closing IRTT server...")
			err := p.irttProcess.Process.Kill()
			if err != nil {
				log.Error().Err(err).Msg("Failed to close IRTT server")
			}
		}
		<-p.irttExited
	}
}

func (p *pinger) GetResultData() map[string][]byte {
	data := make(map[string][]byte)

	if p.icmpPinger != nil {
		icmpPings, err := json.Marshal(p.icmpData)
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to marshal ping result data")
			return nil
		}

		if p.isSender {
			data["icmp-sender.json"] = icmpPings
		} else {
			data["icmp-receiver.json"] = icmpPings
		}
	}

	if p.isSender && len(p.irttResults) > 0 {
		data["irtt-sender.json"] = p.irttResults
	}

	return data
}

func (p *pinger) startIrttStdoutReader() {
	irttStdout, err := p.irttProcess.StdoutPipe()
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to get IRTT stdout pipe")
	}

	stdoutReader := bufio.NewScanner(irttStdout)
	stdoutBuf := bytes.Buffer{}

	for stdoutReader.Scan() {
		line := stdoutReader.Text()
		if p.isSender {
			_, err := stdoutBuf.Write([]byte(line))
			if err != nil {
				log.Fatal().Err(err).Msg("Failed to write IRTT stdout")
			}
		} else {
			log.Debug().Msgf("[IRTT Server]: %s", line)
		}
	}

	err = p.irttProcess.Wait()
	if err != nil && !p.stopping {
		log.Fatal().Err(err).Msg("IRTT process exited with error")
	}

	if p.isSender {
		p.irttResults = stdoutBuf.Bytes()
	}

	p.irttExited <- struct{}{}
}
