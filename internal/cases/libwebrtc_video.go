package cases

import (
	"bufio"
	"encoding/json"
	"os"
	"os/exec"
	"path"
	"strconv"
	"strings"
	"sync"
	"time"
	"webrtc-bench/internal/cases/stats"
	"webrtc-bench/internal/results"

	"github.com/rs/zerolog/log"
)

type CaseVideoLibWebRTC struct {
	sendSignal          func(signalType PeerSignalType, data []byte) error
	statCollector       stats.StatCollector
	process             *exec.Cmd
	stdinWriter         *bufio.Writer
	stdoutReader        *bufio.Scanner
	stderrReader        *bufio.Scanner
	processMutex        sync.Mutex
	isSender            bool
	isStopping          bool
	isUsingFFMpegOutput bool

	probes        []probeAction
	guardTriggers []time.Time
}

type gccStatsSignal struct {
	LossTargetBitrate       uint32
	AverageLoss             float64
	DelayTargetBitrate      uint32
	DelayMeasurement        float64
	DelayTrend              float64
	DelayThreshold          float64
	Usage                   int
	State                   int
	DetectedReconfiguration bool
}

type statTypeInterface struct {
	Type string
}

type signalOutboundRTP struct {
	Timestamp                float64
	PacketsSent              uint64
	BytesSent                uint64
	RetransmittedPacketsSent uint64
	RetransmittedBytesSent   uint64
	HeaderBytesSent          uint64
	TargetBitrate            uint32
	FramesSent               uint64
	FIRCount                 uint32
	PLICount                 uint32
	NACKCount                uint32
}

type signalInboundRTP struct {
	Timestamp                    float64
	Jitter                       float64
	PacketsLost                  uint64
	PacketsReceived              uint64
	BytesReceived                uint64
	HeaderBytesReceived          uint64
	RetransmittedPacketsReceived uint64
	RetransmittedBytesReceived   uint64
	FramesReceived               uint64
	FramesDropped                uint64
	KeyFramesDecoded             uint32
	FreezeCount                  uint32
	TotalFreezesDuration         float32
	LastPacketReceivedTimestamp  float64
	FIRCount                     uint32
	PLICount                     uint32
	NACKCount                    uint32
}

type signalRemoteOutboundRTP struct {
	PacketsSent uint64
	BytesSent   uint64
	ReportsSent uint64
}

type signalRemoteInboundRTP struct {
	Jitter        float64
	PacketsLost   uint64
	RoundTripTime float64
}

type probeAction struct {
	Time   time.Time
	Values []int64
}

func (c *CaseVideoLibWebRTC) Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error, statCollector stats.StatCollector) error {
	c.sendSignal = sendSignal
	c.statCollector = statCollector
	c.isSender = config.SendOffer
	c.isStopping = false

	cwd, err := os.Getwd()
	if err != nil {
		return err
	}

	bitrateStr, ok := config.AdditionalConfig["bitrate"]
	if !ok {
		bitrateStr = "10000"
	}

	targetFpsStr, ok := config.AdditionalConfig["target_fps"]
	if !ok {
		targetFpsStr = "60"
	}

	args := []string{
		"--sender", strconv.FormatBool(config.SendOffer),
		"--bitrate", bitrateStr, "--ice", config.ICEServers[0],
		"--stat-interval", strconv.Itoa(int(time.Duration(config.StatInterval).Milliseconds())),
		"--target-fps", targetFpsStr,
	}

	if val, ok := config.AdditionalConfig["use_ffmpeg_source"]; ok && val == "true" {
		args = append(args, "--use-ffmpeg-source", "true")
		if sourceVal, ok := config.AdditionalConfig["ffmpeg_source_file"]; ok {
			args = append(args, "--ffmpeg-source-file", sourceVal)
		} else {
			args = append(args, "--ffmpeg-source-file", path.Join(cwd, "testdata", "webcam.mp4"))
		}
	}

	if val, ok := config.AdditionalConfig["use_ffmpeg_output"]; ok && val == "true" {
		args = append(args, "--use-ffmpeg-output", "true")
		c.isUsingFFMpegOutput = true
	}

	if val, ok := config.AdditionalConfig["use_real_codec"]; ok {
		args = append(args, "--use-real-codec", val)
	}

	if val, ok := config.AdditionalConfig["min_jitter_buffer_ms"]; ok && val == "true" {
		args = append(args, "--min-jitter-buffer-ms", val)
	}

	var fieldTrials []string
	for key, val := range config.AdditionalConfig {
		if strings.HasPrefix(key, "FieldTrial:") {
			fieldTrialKey := strings.TrimPrefix(key, "FieldTrial:")
			fieldTrials = append(fieldTrials, fieldTrialKey+"/"+val)
		}
	}
	if len(fieldTrials) > 0 {
		args = append(args, "--field-trials", strings.Join(fieldTrials, "/")+"/")
	}

	c.process = exec.Command("bin/gcc_tester", args...)
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
		var latestGCCStats *results.GCCStats
		var guardState *string
		var msSinceLastReport *int
		for c.stdoutReader.Scan() {
			if c.isStopping {
				return
			}
			line := c.stdoutReader.Text()
			if strings.HasPrefix(line, "SIGNAL/") {
				if strings.HasPrefix(line, "SIGNAL/SDP/") {
					err := sendSignal(PeerSignalTypeSDP, []byte(strings.TrimPrefix(line, "SIGNAL/SDP/")))
					if err != nil {
						log.Error().Err(err).Msgf("Error sending signal")
						return
					}
				} else if strings.HasPrefix(line, "SIGNAL/STATS/") {
					var statArr []json.RawMessage
					err := json.Unmarshal([]byte(line[13:]), &statArr)
					if err != nil {
						log.Error().Err(err).Msgf("Error unmarshaling stats array")
						continue
					}

					var inboundRTP *signalInboundRTP
					var outboundRTP *signalOutboundRTP
					var remoteInboundRTP *signalRemoteInboundRTP
					var remoteOutboundRTP *signalRemoteOutboundRTP
					for _, stat := range statArr {
						var typeIf statTypeInterface
						err = json.Unmarshal(stat, &typeIf)
						if err != nil {
							log.Error().Err(err).Msgf("Error unmarshaling stat type")
							continue
						}

						switch typeIf.Type {
						case "inbound-rtp":
							err = json.Unmarshal(stat, &inboundRTP)
							if err != nil {
								log.Error().Err(err).Msgf("Error unmarshaling inbound-rtp part")
								continue
							}
						case "outbound-rtp":
							err = json.Unmarshal(stat, &outboundRTP)
							if err != nil {
								log.Error().Err(err).Msgf("Error unmarshaling inbound-rtp part")
								continue
							}
						case "remote-inbound-rtp":
							err = json.Unmarshal(stat, &remoteInboundRTP)
							if err != nil {
								log.Error().Err(err).Msgf("Error unmarshaling inbound-rtp part")
								continue
							}
						case "remote-outbound-rtp":
							err = json.Unmarshal(stat, &remoteOutboundRTP)
							if err != nil {
								log.Error().Err(err).Msgf("Error unmarshaling inbound-rtp part")
								continue
							}
						}

					}
					if latestGCCStats != nil {
						latestGCCStats.MsSinceLastReport = msSinceLastReport
						latestGCCStats.GuardState = guardState
					}
					statLine := convertSignalsToStatLine(inboundRTP, outboundRTP, remoteInboundRTP, remoteOutboundRTP, latestGCCStats)
					c.statCollector.RecordRow(statLine)
				} else if strings.HasPrefix(line, "SIGNAL/GCC/") {
					if !c.isSender {
						continue
					}
					gccStatJson := line[11:]
					stat := gccStatsSignal{}
					err := json.Unmarshal([]byte(gccStatJson), &stat)
					if err != nil {
						log.Error().Msgf("Error unmarshaling GCC stats: %s", err)
						continue
					}

					converted := convertSignalToGCCStats(stat)
					latestGCCStats = &converted
				} else if strings.HasPrefix(line, "SIGNAL/GUARD/") {
					statString := line[13:]
					parts := strings.Split(statString, ";")
					if len(parts) != 2 {
						log.Error().Msgf("Error parsing signal guard stats: %s", statString)
						continue
					}
					newMsSinceLastReport, err := strconv.Atoi(parts[0])
					if err != nil {
						log.Error().Msgf("Error parsing signal guard ms: %s", parts[0])
						continue
					}

					if latestGCCStats != nil {
						msSinceLastReport = &newMsSinceLastReport
						newGuardState := parts[1]
						if guardState != nil && *guardState != newGuardState && newGuardState == "confirmed_gap" {
							c.guardTriggers = append(c.guardTriggers, time.Now())
						}
						guardState = &newGuardState
					}
				} else if strings.HasPrefix(line, "SIGNAL/PROBE/") {
					probeValues := strings.Split(line[13:], "-")
					p := probeAction{
						Time:   time.Now(),
						Values: []int64{},
					}
					for _, value := range probeValues {
						valInt, err := strconv.ParseInt(value, 10, 64)
						if err != nil {
							return
						}
						p.Values = append(p.Values, valInt)
					}
					c.probes = append(c.probes, p)
				} else {
					log.Error().Msgf("Unknown signal: %s", line)
				}
			} else {
				log.Debug().Msgf("[libwebrtc] %s", line)
			}
		}
		err := c.process.Wait()
		if err != nil && !c.isStopping {
			log.Fatal().Err(err).Msgf("Process exited with error")
		}
	}()

	go func() {
		for c.stderrReader.Scan() {
			if c.isStopping {
				return
			}
			line := c.stderrReader.Text()
			if strings.Contains(line, "iContinualSkipFrames(") {
				continue
			}
			if strings.HasPrefix(line, "(") {
				log.Debug().Msgf("[libwebrtc] stderr: %s", line)
			} else {
				log.Warn().Msgf("[libwebrtc] stderr: %s", line)
			}
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

	c.isStopping = true
	if _, err := c.stdinWriter.WriteString("STOP\n"); err != nil {
		log.Info().Err(err).Msgf("Failed to send stop command to libwebrtc")
	}
	_ = c.stdinWriter.Flush()

	if c.process != nil && c.process.Process != nil {
		_ = c.process.Wait()
		if !c.process.ProcessState.Exited() {
			log.Error().Msgf("LibWebRTC process did not exit, trying to kill!")
			_ = c.process.Process.Kill()
		}
		if !c.process.ProcessState.Exited() {
			log.Fatal().Msgf("LibWebRTC process did not exit!")
		}
		log.Info().Msgf("LibWebRTC process exited!")
	}
}

func convertSignalToGCCStats(signal gccStatsSignal) results.GCCStats {
	usage := ""
	switch signal.Usage {
	case 0:
		usage = "normal"
	case 1:
		usage = "underusing"
	case 2:
		usage = "overusing"
	case 3:
		usage = "last"
	}

	state := ""
	switch signal.State {
	case 0:
		state = "increasing"
	case 1:
		state = "increase_using_padding"
	case 2:
		state = "decreasing"
	case 3:
		state = "delay_based_estimate"
	}

	return results.GCCStats{
		LossTargetBitrate:       signal.LossTargetBitrate,
		AverageLoss:             signal.AverageLoss,
		DelayTargetBitrate:      signal.DelayTargetBitrate,
		DelayMeasurement:        signal.DelayMeasurement,
		DelayEstimate:           signal.DelayTrend,
		DelayThreshold:          signal.DelayThreshold,
		Usage:                   usage,
		State:                   state,
		DetectedReconfiguration: &signal.DetectedReconfiguration,
	}
}

func (c *CaseVideoLibWebRTC) GetExtraResultFiles() *map[string][]byte {
	extraResultFiles := make(map[string][]byte)
	if c.probes != nil && len(c.probes) > 0 {
		marshal, err := json.Marshal(c.probes)
		if err != nil {
			log.Error().Err(err).Msgf("Error marshaling probes")
			return nil
		}
		extraResultFiles["probes.json"] = marshal
	}
	if c.guardTriggers != nil && len(c.guardTriggers) > 0 {
		marshal, err := json.Marshal(c.guardTriggers)
		if err != nil {
			log.Error().Err(err).Msgf("Error marshaling guard")
			return nil
		}
		extraResultFiles["guard_triggers.json"] = marshal
	}
	if len(extraResultFiles) > 0 {
		return &extraResultFiles
	}
	return nil
}

func (c *CaseVideoLibWebRTC) GetLargeResultFiles() *map[string]string {
	if c.isUsingFFMpegOutput && !c.isSender {
		cwd, err := os.Getwd()
		if err != nil {
			log.Error().Err(err).Msgf("Error getting current working directory")
			return nil
		}
		outputFilePath := path.Join(cwd, "received_video.ts")

		return &map[string]string{
			"received_video.ts": outputFilePath,
		}
	}
	return nil
}

func convertSignalsToStatLine(inboundRTP *signalInboundRTP, outboundRTP *signalOutboundRTP,
	remoteInboundRTP *signalRemoteInboundRTP, _ *signalRemoteOutboundRTP, gccStats *results.GCCStats) results.ResultRow {

	resultRow := results.ResultRow{}
	if inboundRTP != nil {
		resultRow.Timestamp = time.UnixMicro(int64(inboundRTP.Timestamp))
		resultRow.InboundRTP = &results.ResultRowInboundRTP{
			PacketsReceived:              inboundRTP.PacketsReceived,
			PacketsLost:                  int64(inboundRTP.PacketsLost),
			Jitter:                       inboundRTP.Jitter,
			MillisSinceLastPacket:        uint64(inboundRTP.Timestamp - inboundRTP.LastPacketReceivedTimestamp),
			HeaderBytesReceived:          inboundRTP.HeaderBytesReceived,
			BytesReceived:                inboundRTP.BytesReceived,
			FIRCount:                     inboundRTP.FIRCount,
			PLICount:                     inboundRTP.PLICount,
			NACKCount:                    inboundRTP.NACKCount,
			FramesReceived:               &inboundRTP.FramesReceived,
			FramesDropped:                &inboundRTP.FramesDropped,
			KeyFramesDecoded:             &inboundRTP.KeyFramesDecoded,
			FreezeCount:                  &inboundRTP.FreezeCount,
			TotalFreezesDuration:         &inboundRTP.TotalFreezesDuration,
			RetransmittedBytesReceived:   &inboundRTP.RetransmittedBytesReceived,
			RetransmittedPacketsReceived: &inboundRTP.RetransmittedPacketsReceived,
		}
	}
	if outboundRTP != nil {
		resultRow.Timestamp = time.UnixMicro(int64(outboundRTP.Timestamp))
		resultRow.OutboundRTP = &results.ResultRowOutboundRTP{
			PacketsSent:     outboundRTP.PacketsSent,
			BytesSent:       outboundRTP.BytesSent,
			HeaderBytesSent: outboundRTP.HeaderBytesSent,
			NACKCount:       outboundRTP.NACKCount,
			FIRCount:        outboundRTP.FIRCount,
			PLICount:        outboundRTP.FIRCount,
			FramesSent:      &outboundRTP.FramesSent,
			TargetBitrate:   &outboundRTP.TargetBitrate,
		}
	}
	if remoteInboundRTP != nil {
		resultRow.OutboundRTP.RoundTripTime = remoteInboundRTP.RoundTripTime
	}

	resultRow.GCCStats = gccStats

	return resultRow
}
