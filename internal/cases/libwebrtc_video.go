package cases

import (
	"bufio"
	"github.com/rs/zerolog/log"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
	"webrtc-bench/internal/cases/stats"
)

type CaseVideoLibWebRTC struct {
	sendSignal    func(signalType PeerSignalType, data []byte) error
	statCollector stats.StatCollector
	process       *exec.Cmd
	stdinWriter   *bufio.Writer
	stdoutReader  *bufio.Scanner
	stderrReader  *bufio.Scanner
	processMutex  sync.Mutex
}

func (c *CaseVideoLibWebRTC) Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error, statCollector stats.StatCollector) error {
	c.sendSignal = sendSignal
	c.statCollector = statCollector

	cwd, err := os.Getwd()
	if err != nil {
		return err
	}

	bitrateStr, ok := config.AdditionalConfig["bitrate"]
	if !ok {
		bitrateStr = "10000"
	}

	c.process = exec.Command("bin/gcc_tester", "--sender", strconv.FormatBool(config.SendOffer),
		"--bitrate", bitrateStr, "--ice", config.ICEServers[0],
		"--stat-interval", strconv.Itoa(int(time.Duration(config.StatInterval).Milliseconds())))
	c.process.Dir = cwd
	log.Info().Msgf("Starting external process with command '%v'", c.process.String())

	stdin, err := c.process.StdinPipe()
	if err != nil {
		return err
	}
	c.stdinWriter = bufio.NewWriter(stdin)

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

	if err := c.process.Start(); err != nil {
		return err
	}

	go func() {
		for c.stdoutReader.Scan() {
			line := c.stdoutReader.Text()
			if strings.HasPrefix(line, "SIGNAL/SDP/") {
				err := sendSignal(PeerSignalTypeSDP, []byte(strings.TrimPrefix(line, "SIGNAL/SDP/")))
				if err != nil {
					log.Error().Msgf("Error sending signal: %s", err)
					return
				}
			}
			log.Debug().Msgf("[libwebrtc] %s", line)
		}
		err := c.process.Wait()
		if err != nil {
			log.Fatal().Msgf("Process exited with error: %s", err)
		}
	}()

	go func() {
		for c.stderrReader.Scan() {
			line := c.stderrReader.Text()
			log.Warn().Msgf("[libwebrtc] stderr: %s", line)
		}
	}()

	return nil
}

func (c *CaseVideoLibWebRTC) Start() error {
	c.processMutex.Lock()
	defer c.processMutex.Unlock()

	// Send the "START" command to the process
	if _, err := c.stdinWriter.WriteString("START\n"); err != nil {
		return err
	}
	return c.stdinWriter.Flush()
}

func (c *CaseVideoLibWebRTC) OnReceiveSignal(_ PeerSignalType, message []byte) error {
	c.processMutex.Lock()
	defer c.processMutex.Unlock()

	command := "SDP/" + string(message)
	if _, err := c.stdinWriter.WriteString(command + "\n"); err != nil {
		return err
	}
	return c.stdinWriter.Flush()
}

func (c *CaseVideoLibWebRTC) Stop() {
	c.processMutex.Lock()
	defer c.processMutex.Unlock()

	if c.process != nil && c.process.Process != nil {
		_ = c.process.Process.Kill()
		c.process = nil
	}
}
