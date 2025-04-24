package management

import (
	"encoding/json"
	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
	"net/http"
	"time"
	"webrtc-bench/internal/cases"
)

type Client interface {
	Start()
	SendMessage(msgType MessageType, content interface{}) error
}

type client struct {
	ServerAddress     string
	ClientName        string
	AuthenticationKey string
	SendChan          chan []byte

	CurrentCase cases.PeerCaseExecutor
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
				_ = conn.SetWriteDeadline(time.Now().Add(time.Second * 3))
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
				log.Error().Err(err).Msg("Error reading from Management WS")
				return
			}

			switch msgType {
			case websocket.PingMessage:
				err = conn.WriteMessage(websocket.PongMessage, nil)
				if err != nil {
					log.Error().Err(err).Msg("Error writing to Management WS")
					return
				}
			case websocket.BinaryMessage:
				outerMsg := MessageContainer{}
				err := json.Unmarshal(msg, &outerMsg)
				if err != nil {
					log.Warn().Err(err).Msg("Could not parse received WS message")
					_ = conn.Close()
					return
				}

				switch outerMsg.MessageType {
				case MessageTypeRegisterClientOk:
					log.Info().Msg("Client registration succeeded")
				case MessageTypeConfigureClient:
					innerMsg := MessageConfigureClient{}
					err := json.Unmarshal(outerMsg.Data, &innerMsg)
					if err != nil {
						log.Warn().Err(err).Msg("Could not parse received inner WS message")
						_ = conn.Close()
						return
					}
					c.configureCase(innerMsg)
				case MessageTypeStartCaseExecution:
					if c.CurrentCase == nil {
						log.Error().Msg("Cannot start execution, no case configured!")
						continue
					}
					err := c.CurrentCase.Start()
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
					log.Info().Msg("Case execution stopped")
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
		}
	}()
}

func (c *client) SendMessage(msgType MessageType, content interface{}) error {
	innerMsg, err := json.Marshal(content)
	if err != nil {
		return err
	}

	container := MessageContainer{
		MessageType: msgType,
		Data:        innerMsg,
	}

	msgData, err := json.Marshal(container)
	if err != nil {
		return err
	}

	c.SendChan <- msgData
	return nil
}

func (c *client) configureCase(configMsg MessageConfigureClient) {
	switch configMsg.CaseType {
	case cases.CaseTypeConnect:
		c.CurrentCase = &cases.CaseConnect{}
	default:
		log.Fatal().Msgf("Unrecognized caseType: %s", configMsg.CaseType)
	}

	err := c.CurrentCase.Configure(configMsg.Config, func(signalType cases.PeerSignalType, data []byte) error {
		log.Debug().Msgf("OnSendSignal: [%s] %s", signalType, data)
		return c.SendMessage(MessageTypePeerSignal, MessagePeerSignal{SignalType: signalType, Data: data})
	})
	if err != nil {
		log.Fatal().Err(err).Msg("Error configuring case")
		return
	}
	log.Info().Msgf("Successfully configured case %s", configMsg.CaseType)
}
