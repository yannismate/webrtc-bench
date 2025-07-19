package cases

import (
	"bufio"
	"bytes"
	"github.com/rs/zerolog/log"
	"math"
	"os"
	"os/exec"
	"strconv"
	"sync"
	"time"
	"webrtc-bench/internal/cases/stats"
)

type CaseIPerfUDP struct {
	Duration     time.Duration
	process      *exec.Cmd
	stdoutReader *bufio.Scanner
	stderrReader *bufio.Scanner
	processMutex sync.Mutex
	isSender     bool
	isStopping   bool
	outBuf       bytes.Buffer
}

func (c *CaseIPerfUDP) Configure(config PeerCaseConfig, _ func(signalType PeerSignalType, data []byte) error, _ stats.StatCollector) error {
	c.isSender = config.SendOffer
	c.isStopping = false

	cwd, err := os.Getwd()
	if err != nil {
		return err
	}

	bitrateStr, ok := config.AdditionalConfig["bitrate"]
	if !ok {
		bitrateStr = "10M"
	}

	targetIP, ok := config.AdditionalConfig["target_ip"]
	if !ok {
		targetIP = "135.220.32.39"
	}

	// Finish iperf slightly early to capture output
	lengthSeconds := int(math.Ceil(c.Duration.Seconds()) - 2)

	var args []string
	if c.isSender {
		args = append(args, "-c", targetIP, "-p", "5002", "-t", strconv.Itoa(lengthSeconds), "-u", "-b", bitrateStr, "-i", "1", "--json")
	} else {
		args = append(args, "-s", "-p", "5002", "-i", "1", "--json")
	}

	c.process = exec.Command("iperf3", args...)
	c.process.Dir = cwd
	log.Info().Msgf("Starting external process with command '%v'", c.process.String())

	stdout, err := c.process.StdoutPipe()
	if err != nil {
		return err
	}
	c.stdoutReader = bufio.NewScanner(stdout)

	stderr, err := c.process.StderrPipe()
	if err != nil {
		return err
	}
	c.stderrReader = bufio.NewScanner(stderr)

	if !c.isSender {
		if err := c.process.Start(); err != nil {
			return err
		}
	}
	c.outBuf = bytes.Buffer{}

	go func() {
		for c.stdoutReader.Scan() {
			line := c.stdoutReader.Text()
			log.Debug().Msgf("[iperf3] %s", line)
			_, err := c.outBuf.WriteString(line + "\n")
			if err != nil {
				log.Error().Err(err).Str("line", line).Msg("Failed to write to temp file")
			}
		}
		err := c.process.Wait()
		if err != nil && !c.isStopping {
			log.Fatal().Err(err).Msgf("Process exited with error")
		}
	}()

	go func() {
		for c.stderrReader.Scan() {
			line := c.stderrReader.Text()
			log.Warn().Msgf("[iperf3] %s", line)
		}
	}()

	return nil
}

func (c *CaseIPerfUDP) Start() error {
	c.processMutex.Lock()
	defer c.processMutex.Unlock()

	if c.isSender {
		return c.process.Start()
	}
	return nil
}

func (c *CaseIPerfUDP) OnReceiveSignal(_ PeerSignalType, _ []byte) error {
	return nil
}

func (c *CaseIPerfUDP) Stop() {
	c.processMutex.Lock()
	defer c.processMutex.Unlock()

	c.isStopping = true
	if c.process != nil && c.process.Process != nil {
		_ = c.process.Process.Kill()
	}
}

func (c *CaseIPerfUDP) GetExtraResultFiles() *map[string][]byte {
	iperfFileName := "iperf-receiver.json"
	if c.isSender {
		iperfFileName = "iperf-sender.json"
	}

	val := map[string][]byte{
		iperfFileName: c.outBuf.Bytes(),
	}
	return &val
}
