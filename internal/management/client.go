package management

import (
	"bufio"
	"context"
	"encoding/json"
	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
	"webrtc-bench/internal/cases"
	"webrtc-bench/internal/cases/stats"
	"webrtc-bench/internal/dishy"
	"webrtc-bench/internal/results"
	"webrtc-bench/internal/util"
)

type Client interface {
	Start()
	Stop()
	SendMessage(msgType MessageType, content interface{})
}

type client struct {
	ServerAddress     string
	ClientName        string
	AuthenticationKey string
	SendChan          chan []byte

	CurrentCase         cases.PeerCaseExecutor
	CurrentCaseConfig   cases.PeerCaseConfig
	CurrentResultWriter results.ParquetResultsWriter
	CurrentCaseMetadata util.TestMetadata

	dishyClient                 dishy.DeviceClient
	dishyAvailable              bool
	dishyLat, dishyLong         float64
	dishyObstructionData        *obstructionData
	dishyStopDataCollectionChan chan bool
	dishyDataCollectionStopped  sync.WaitGroup

	runningProcesses []*os.Process
}

type obstructionData struct {
	ReferenceFrame  string
	NumRows         int
	NumColumns      int
	ObstructionData []obstructionDataEntry
}

type obstructionDataEntry struct {
	Time            time.Time
	SNR             []snrEntry
	MinElevationDeg float32
	MaxThetaDeg     float32
}

type snrEntry struct {
	Index int
	Value float32
}

func NewClient(serverAddress string, clientName string, authenticationKey string) Client {
	return &client{
		ServerAddress:     serverAddress,
		ClientName:        clientName,
		AuthenticationKey: authenticationKey,
		dishyAvailable:    false,
	}
}

func (c *client) Start() {
	c.dishySetup()

	headers := http.Header{}
	headers.Set(AuthenticationKeyHeader, c.AuthenticationKey)

	log.Info().Msgf("Connecting to management server at %s as client %s", c.ServerAddress, c.ClientName)
	conn, _, err := websocket.DefaultDialer.Dial("ws://"+c.ServerAddress, headers)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to management server")
	}

	sendChan := make(chan []byte, 3)
	c.SendChan = sendChan

	go c.SendMessage(MessageTypeRegisterClient, MessageRegisterClient{ClientName: c.ClientName})

	if err != nil {
		log.Fatal().Err(err).Msg("Failed to send client registration message")
		return
	}

	go func() {
		ticker := time.NewTicker(time.Second * 5)
		for {
			select {
			case msg, ok := <-c.SendChan:
				if !ok {
					_ = conn.WriteMessage(websocket.CloseMessage, nil)
					log.Warn().Msg("SendChan closed before message was queued.")
					return
				}

				err := conn.WriteMessage(websocket.BinaryMessage, msg)
				if err != nil {
					log.Error().Err(err).Msg("Failed to send message to management server.")
					_ = conn.Close()
					return
				}
			case <-ticker.C:
				if err := conn.WriteMessage(websocket.PingMessage, nil); err != nil {
					_ = conn.Close()
					log.Warn().Err(err).Msg("Could not ping client, closing connection...")
					return
				}
			}
		}
	}()

	go func() {
		defer conn.Close()
		for {
			msgType, msg, err := conn.ReadMessage()
			if err != nil {
				log.Fatal().Err(err).Msg("Error reading from Management WS")
				return
			}

			if msgType != websocket.BinaryMessage {
				continue
			}

			outerMsg := MessageContainer{}
			err = json.Unmarshal(msg, &outerMsg)
			if err != nil {
				log.Fatal().Err(err).Msg("Could not parse received WS message")
				_ = conn.Close()
				return
			}

			switch outerMsg.MessageType {
			case MessageTypeRegisterClientOk:
				log.Info().Msg("Client registration succeeded")
				c.SendMessage(MessageTypeClientStateUpdate, MessageClientStateUpdate{ClientStateRegistered})
			case MessageTypeShutdown:
				log.Info().Msg("Orchestrator requested shutdown")
				os.Exit(0)
			case MessageTypeConfigureClient:
				innerMsg := MessageConfigureClient{}
				err := json.Unmarshal(outerMsg.Data, &innerMsg)
				if err != nil {
					log.Warn().Err(err).Msg("Could not parse received inner WS message")
					_ = conn.Close()
					return
				}
				c.SendMessage(MessageTypeClientStateUpdate, MessageClientStateUpdate{ClientStateConfiguring})
				c.configureCase(innerMsg)
				c.SendMessage(MessageTypeClientStateUpdate, MessageClientStateUpdate{ClientStateTestReady})
			case MessageTypeStartCaseExecution:
				if c.CurrentCase == nil {
					log.Error().Msg("Cannot start execution, no case configured!")
					continue
				}
				if c.dishyAvailable {
					c.startObstructionMapTracking()
				}
				if c.CurrentCaseConfig.ConfigurationCommands != nil {
					go func() {
						cmdSecTicker := time.NewTicker(time.Second)
						secondsPassed := 0
						currentCaseStarted := c.CurrentCaseMetadata.TimeStarted

						for {
							select {
							case <-cmdSecTicker.C:
								secondsPassed++

								if c.CurrentCase == nil || c.CurrentCaseMetadata.TimeStarted != currentCaseStarted {
									return
								}

								if cmds, ok := (*c.CurrentCaseConfig.ConfigurationCommands)["t"+strconv.Itoa(secondsPassed)]; ok {
									for _, cmd := range cmds {
										c.executeCommand(cmd)
									}
								}
							}
						}
					}()
				}

				err := c.CurrentCase.Start()
				c.SendMessage(MessageTypeClientStateUpdate, MessageClientStateUpdate{ClientStateTesting})
				log.Info().Msg("Case execution started")
				if err != nil {
					log.Warn().Err(err).Msg("Error while starting case execution")
					_ = conn.Close()
					return
				}
			case MessageTypeStopCaseExecution:
				if c.CurrentCase == nil {
					log.Error().Msg("Cannot stop execution, no case configured!")
					continue
				}
				c.CurrentCase.Stop()
				if c.dishyAvailable {
					c.stopObstructionMapTracking()
				}
				c.SendMessage(MessageTypeClientStateUpdate, MessageClientStateUpdate{ClientStateTestEnding})
				log.Info().Msg("Case execution stopped")

				if c.CurrentCaseConfig.ConfigurationCommands != nil {
					if cmds, ok := (*c.CurrentCaseConfig.ConfigurationCommands)["post"]; ok {
						for _, cmd := range cmds {
							c.executeCommand(cmd)
						}
					}
				}

				if c.CurrentResultWriter != nil {
					c.CurrentResultWriter.Close()
					file, err := c.CurrentResultWriter.GetResultFile()
					if err != nil {
						log.Fatal().Err(err).Msg("Error getting result file")
						return
					}
					fileData, err := io.ReadAll(file)
					if err != nil {
						log.Fatal().Err(err).Msg("Error reading result file")
						return
					}

					extraFiles := c.CurrentCase.GetExtraResultFiles()
					if c.dishyAvailable {
						dishyData, err := json.Marshal(c.dishyObstructionData)
						if err != nil {
							log.Fatal().Err(err).Msg("Error marshalling dishy data")
							return
						}
						if extraFiles == nil {
							newExtraFiles := make(map[string][]byte)
							extraFiles = &newExtraFiles
						}
						(*extraFiles)["dishy_"+c.ClientName+".json"] = dishyData
					}

					c.SendMessage(MessageTypeResults, MessageResults{
						Metadata:        c.CurrentCaseMetadata,
						FileData:        fileData,
						AdditionalFiles: extraFiles,
					})
				}
				log.Debug().Msgf("Sent case results message.")

				for _, p := range c.runningProcesses {
					if p.Pid == 0 {
						continue
					}
					process, err := os.FindProcess(p.Pid)
					if err != nil || process == nil {
						continue
					}
					log.Warn().Msgf("Case process still running with PID %d, trying to kill...", p.Pid)
					err = process.Kill()
					if err != nil {
						log.Error().Err(err).Msgf("Killing PID %d failed", p.Pid)
					}
				}

				c.SendMessage(MessageTypeClientStateUpdate, MessageClientStateUpdate{ClientStateRegistered})
			case MessageTypePeerSignal:
				if c.CurrentCase == nil {
					log.Error().Msg("Cannot receive peer signal, no case configured!")
					continue
				}
				innerMsg := MessagePeerSignal{}
				err := json.Unmarshal(outerMsg.Data, &innerMsg)
				if err != nil {
					log.Warn().Err(err).Msg("Could not parse received inner WS message")
					_ = conn.Close()
					return
				}
				err = c.CurrentCase.OnReceiveSignal(innerMsg.SignalType, innerMsg.Data)
				if err != nil {
					log.Error().Err(err).Msg("Error while handling peer signal")
					return
				}
			}

		}
	}()
}

func (c *client) dishySetup() {
	grpcClient, err := grpc.NewClient("192.168.100.1:9200", grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatal().Err(err).Msg("Error creating dishy grpc client")
		return
	}
	c.dishyClient = dishy.NewDeviceClient(grpcClient)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	res, err := c.dishyClient.Handle(ctx, &dishy.Request{
		Request: &dishy.Request_DishGetObstructionMap{},
	})
	if err != nil {
		log.Info().Err(err).Msg("Dishy not found.")
		return
	}

	obMapRes := res.Response.(*dishy.Response_DishGetObstructionMap)
	log.Info().Msgf("Dishy found! Obstruction map reference frame: %v", obMapRes.DishGetObstructionMap.MapReferenceFrame.String())
	c.dishyAvailable = true
	c.dishyObstructionData = &obstructionData{
		ReferenceFrame: obMapRes.DishGetObstructionMap.MapReferenceFrame.String(),
		NumRows:        int(obMapRes.DishGetObstructionMap.NumRows),
		NumColumns:     int(obMapRes.DishGetObstructionMap.NumCols),
	}
}

func (c *client) startObstructionMapTracking() {
	c.dishyStopDataCollectionChan = make(chan bool)
	c.dishyObstructionData.ObstructionData = make([]obstructionDataEntry, 0)
	go func() {
		c.dishyDataCollectionStopped.Add(1)
		defer c.dishyDataCollectionStopped.Done()

		ticker := time.NewTicker(time.Second * 1)
		n := 0
		for {
			select {
			case _, _ = <-c.dishyStopDataCollectionChan:
				log.Debug().Msg("Dishy data collection stop signal received.")
				return
			case <-ticker.C:
				if n == 0 {
					log.Debug().Msg("Resetting obstruction map")
					ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
					// reset obstruction map every 14 seconds
					_, err := c.dishyClient.Handle(ctx, &dishy.Request{
						Request: &dishy.Request_DishClearObstructionMap{},
					})
					cancel()
					if err != nil {
						log.Info().Err(err).Msg("Dishy obstruction map clearing failed.")
						return
					}
				}

				log.Debug().Msg("Fetching current obstruction map")
				ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
				// reset obstruction map every 14 seconds
				res, err := c.dishyClient.Handle(ctx, &dishy.Request{
					Request: &dishy.Request_DishGetObstructionMap{},
				})
				cancel()
				if err != nil {
					log.Info().Err(err).Msg("Dishy obstruction map fetching failed.")
					return
				}

				obMapRes := res.Response.(*dishy.Response_DishGetObstructionMap)
				var entries []snrEntry
				for i, val := range obMapRes.DishGetObstructionMap.Snr {
					if val != -1 {
						entries = append(entries, snrEntry{
							Index: i,
							Value: val,
						})
					}
				}
				c.dishyObstructionData.ObstructionData = append(c.dishyObstructionData.ObstructionData, obstructionDataEntry{
					Time:            time.Now(),
					SNR:             entries,
					MinElevationDeg: obMapRes.DishGetObstructionMap.MinElevationDeg,
					MaxThetaDeg:     obMapRes.DishGetObstructionMap.MaxThetaDeg,
				})

				n = (n + 1) % 14
			}
		}
	}()
}

func (c *client) stopObstructionMapTracking() {
	log.Debug().Msg("Stopping dishy obstruction map tracking...")
	close(c.dishyStopDataCollectionChan)
	c.dishyDataCollectionStopped.Wait()
	log.Debug().Msg("Obstruction map tracking stopped.")
}

func (c *client) Stop() {
	if c.CurrentCase != nil {
		c.CurrentCase.Stop()
	}
}

func (c *client) SendMessage(msgType MessageType, content interface{}) {
	innerMsg, err := json.Marshal(content)
	if err != nil {
		log.Panic().Err(err).Msg("Could not marshal inner message to JSON")
	}
	container := MessageContainer{
		MessageType: msgType,
		Data:        innerMsg,
	}

	msgData, err := json.Marshal(container)
	if err != nil {
		log.Panic().Err(err).Msg("Could not marshal container to JSON")
	}

	c.SendChan <- msgData
}

func (c *client) configureCase(configMsg MessageConfigureClient) {
	c.CurrentCaseConfig = configMsg.Config
	if configMsg.Config.Implementation == cases.PeerImplementationPion {
		c.CurrentCaseMetadata = util.GetPionTestMetadata()
		switch configMsg.CaseType {
		case cases.CaseTypeConnect:
			c.CurrentCase = &cases.CaseConnectPion{}
		case cases.CaseTypeVideo:
			c.CurrentCase = &cases.CaseVideoPion{}
		default:
			log.Fatal().Msgf("Unrecognized caseType: %s", configMsg.CaseType)
		}
	} else if configMsg.Config.Implementation == cases.PeerImplementationChrome {
		c.CurrentCaseMetadata = util.GetChromeTestMetadata()
		switch configMsg.CaseType {
		case cases.CaseTypeConnect:
			c.CurrentCase = &cases.CaseConnectChrome{}
		case cases.CaseTypeVideo:
			c.CurrentCase = &cases.CaseVideoChrome{}
		default:
			log.Fatal().Msgf("Unrecognized caseType: %s", configMsg.CaseType)
		}
	} else if configMsg.Config.Implementation == cases.PeerImplementationLibWebRTC {
		c.CurrentCaseMetadata = util.GetLibWebRTCTestMetadata()
		switch configMsg.CaseType {
		case cases.CaseTypeVideo:
			c.CurrentCase = &cases.CaseVideoLibWebRTC{}
		default:
			log.Fatal().Msgf("Unrecognized caseType: %s", configMsg.CaseType)
		}
	} else if configMsg.Config.Implementation == cases.PeerImplementationIPerf {
		if configMsg.CaseType != cases.CaseTypeBandwidthMeasurement {
			log.Fatal().Msgf("Unrecognized caseType: %s", configMsg.CaseType)
		}
		c.CurrentCase = &cases.CaseIPerfUDP{Duration: time.Duration(configMsg.CaseDuration)}
	} else {
		log.Fatal().Msgf("Unrecognized implementation type: %s", configMsg.CaseType)
	}

	resultWriter, err := results.NewParquetResultsWriter()
	if err != nil {
		log.Fatal().Err(err).Msg("Could not create parquet results writer")
		return
	}
	c.CurrentResultWriter = resultWriter

	statCollector := stats.NewStatCollector(resultWriter)
	statCollector.SetInterval(time.Duration(configMsg.Config.StatInterval))

	if configMsg.Config.ConfigurationCommands != nil {
		if cmds, ok := (*configMsg.Config.ConfigurationCommands)["pre"]; ok {
			for _, cmd := range cmds {
				c.executeCommand(cmd)
			}
		}
	}

	err = c.CurrentCase.Configure(configMsg.Config, func(signalType cases.PeerSignalType, data []byte) error {
		log.Debug().Msgf("OnSendSignal: [%s] %s", signalType, data)
		c.SendMessage(MessageTypePeerSignal, MessagePeerSignal{SignalType: signalType, Data: data})
		return nil
	}, statCollector)
	if err != nil {
		log.Fatal().Err(err).Msg("Error configuring case")
		return
	}
	log.Info().Msgf("Successfully configured case %s", configMsg.CaseType)
}

func (c *client) executeCommand(cmd string) {
	ignoreErr := strings.HasPrefix(cmd, "!")
	runAsync := strings.HasPrefix(cmd, "~")
	cmd = strings.TrimPrefix(cmd, "!")
	cmd = strings.TrimPrefix(cmd, "~")
	cmdParts := strings.Split(cmd, " ")
	goCmd := exec.Command(cmdParts[0], cmdParts[1:]...)
	if runAsync {
		log.Info().Msgf("Executing command in background: %s", cmd)
		stdout, err := goCmd.StdoutPipe()
		if err != nil {
			log.Fatal().Err(err).Str("command", goCmd.String()).Msg("Error getting command stdout")
			return
		}
		stdoutReader := bufio.NewScanner(stdout)
		go func() {
			for stdoutReader.Scan() {
				log.Debug().Msgf("[BackgroundCommand] stdout: %s", stdoutReader.Text())
			}
			_ = goCmd.Wait()
			for i, proc := range c.runningProcesses {
				if proc.Pid == goCmd.Process.Pid {
					c.runningProcesses = append(c.runningProcesses[:i], c.runningProcesses[i+1:]...)
					break
				}
			}

		}()
		stderr, err := goCmd.StderrPipe()
		if err != nil {
			log.Fatal().Err(err).Str("command", goCmd.String()).Msg("Error getting command stderr")
			return
		}
		stderrReader := bufio.NewScanner(stderr)
		go func() {
			for stderrReader.Scan() {
				log.Warn().Msgf("[BackgroundCommand] stderr: %s", stderrReader.Text())
			}
		}()

		err = goCmd.Start()
		if err != nil {
			log.Fatal().Err(err).Str("command", goCmd.String()).Msg("Error executing command")
			return
		}
		c.runningProcesses = append(c.runningProcesses, goCmd.Process)
		return
	}
	err := goCmd.Run()
	if err != nil {
		if ignoreErr {
			log.Info().Err(err).Msgf("Executed command %s, ignoring error.", cmd)
			return
		}
		log.Fatal().Err(err).Str("command", goCmd.String()).Msg("Error executing command")
		return
	}
	log.Info().Msgf("Executed command: %s", cmd)
}
