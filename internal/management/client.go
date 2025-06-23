package management

import (
	"encoding/json"
	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
	"webrtc-bench/internal/cases"
	"webrtc-bench/internal/cases/stats"
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
}

func NewClient(serverAddress string, clientName string, authenticationKey string) Client {
	return &client{
		ServerAddress:     serverAddress,
		ClientName:        clientName,
		AuthenticationKey: authenticationKey,
	}
}

func (c *client) Start() {
	headers := http.Header{}
	headers.Set(AuthenticationKeyHeader, c.AuthenticationKey)

	conn, _, err := websocket.DefaultDialer.Dial("ws://"+c.ServerAddress, headers)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to management server")
	}

	sendChan := make(chan []byte)
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
					return
				}

				err := conn.WriteMessage(websocket.BinaryMessage, msg)
				if err != nil {
					_ = conn.Close()
					return
				}
			case <-ticker.C:
				_ = conn.SetWriteDeadline(time.Now().Add(time.Second * 10))
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
										executeCommand(cmd)
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
				c.SendMessage(MessageTypeClientStateUpdate, MessageClientStateUpdate{ClientStateTestEnding})
				log.Info().Msg("Case execution stopped")

				if c.CurrentCaseConfig.ConfigurationCommands != nil {
					if cmds, ok := (*c.CurrentCaseConfig.ConfigurationCommands)["post"]; ok {
						for _, cmd := range cmds {
							executeCommand(cmd)
						}
					}
				}

				if c.CurrentResultWriter != nil {
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

					c.SendMessage(MessageTypeResults, MessageResults{
						Metadata: c.CurrentCaseMetadata,
						FileData: fileData,
					})
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
				executeCommand(cmd)
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

func executeCommand(cmd string) {
	ignoreErr := strings.HasPrefix(cmd, "!")
	cmd = strings.TrimPrefix(cmd, "!")
	cmdParts := strings.Split(cmd, " ")
	goCmd := exec.Command(cmdParts[0], cmdParts[1:]...)
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
