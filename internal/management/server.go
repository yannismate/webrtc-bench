package management

import (
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
	"net/http"
	"os"
	"os/signal"
	"path"
	"sync"
	"syscall"
	"time"
)

type Server interface {
	Start()
	SetClientStateUpdateListener(func(string, ClientState))
	SendMessage(clientName string, messageType MessageType, content interface{}) error
	SetCurrentResultPath(path string)
	SetShuttingDown()
}

type server struct {
	ListenAddr string
	// This is not particularly secure over non-HTTPS connections, but it will do for these benchmarks
	AuthenticationKey         string
	Clients                   map[string]wsClient
	ClientStateUpdateListener func(string, ClientState)

	shuttingDown       bool
	currentResultPath  string
	writeResultsWaiter sync.WaitGroup
}

type wsClient struct {
	SendChan           chan []byte
	RegisteredAsClient *string
}

func NewServer(listenAddr string, authenticationKey string) Server {
	return &server{
		ListenAddr:                listenAddr,
		AuthenticationKey:         authenticationKey,
		Clients:                   make(map[string]wsClient),
		ClientStateUpdateListener: func(string, ClientState) {},
		shuttingDown:              false,
	}
}

func (s *server) Start() {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleWs)

	httpServer := &http.Server{
		Addr:    s.ListenAddr,
		Handler: mux,
	}

	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		<-sigChan

		log.Info().Msg("Shutting down HTTP server")
		if err := httpServer.Close(); err != nil {
			log.Fatal().Err(err).Msg("Could not close HTTP server")
			return
		}
	}()
	go func() {
		log.Info().Msgf("Starting control server on %s", s.ListenAddr)
		err := httpServer.ListenAndServe()
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatal().Err(err).Msg("HTTP server stopped unexpectedly")
		}
		os.Exit(0)
	}()
}

func (s *server) SetClientStateUpdateListener(f func(string, ClientState)) {
	s.ClientStateUpdateListener = f
}

func (s *server) getPeerByName(name string) (wsClient, bool) {
	for _, client := range s.Clients {
		if client.RegisteredAsClient != nil && *client.RegisteredAsClient == name {
			return client, true
		}
	}
	return wsClient{}, false
}

func (s *server) SetShuttingDown() {
	s.shuttingDown = true
	s.writeResultsWaiter.Wait()
}

func (s *server) SendMessage(clientName string, msgType MessageType, content interface{}) error {
	peer, ok := s.getPeerByName(clientName)
	if !ok {
		return errors.New("client not found: " + clientName)
	}

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

	peer.SendChan <- msgData
	return nil
}

var upgrader = websocket.Upgrader{}

func (s *server) handleWs(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get(AuthenticationKeyHeader) != s.AuthenticationKey {
		w.WriteHeader(http.StatusUnauthorized)
		return
	}
	c, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Warn().Str("req_addr", r.RemoteAddr).Err(err).Msg("Could not upgrade to websocket connection")
		return
	}

	clientId := uuid.New().String()
	log.Info().Str("client_id", clientId).Msg("Client connected")

	sendChan := make(chan []byte, 3)
	s.Clients[clientId] = wsClient{
		SendChan: sendChan,
	}

	defer func() {
		_ = c.Close()
		disconnectedClient := s.Clients[clientId]
		if disconnectedClient.RegisteredAsClient != nil {
			log.Warn().Str("client_id", clientId).Str("client_name", *disconnectedClient.RegisteredAsClient).Msg("Registered client disconnected")
			s.ClientStateUpdateListener(*disconnectedClient.RegisteredAsClient, ClientStateDisconnected)
		} else {
			log.Info().Str("client_id", clientId).Msg("Client disconnected")
		}
		close(disconnectedClient.SendChan)
		delete(s.Clients, clientId)
	}()

	go func() {
		ticker := time.NewTicker(time.Second * 5)

		for {
			select {
			case msg, ok := <-sendChan:
				if !ok {
					_ = c.WriteMessage(websocket.CloseMessage, nil)
					return
				}

				err := c.WriteMessage(websocket.BinaryMessage, msg)
				if err != nil {
					_ = c.Close()
					return
				}
			case <-ticker.C:
				if err := c.WriteMessage(websocket.PingMessage, nil); err != nil {
					_ = c.Close()
					log.Warn().Err(err).Msg("Could not ping client, closing connection...")
					return
				}
			}
		}
	}()

	for {
		msgType, msg, err := c.ReadMessage()
		if err != nil {
			_ = c.Close()
			if !s.shuttingDown {
				log.Warn().Err(err).Msg("Could not read WS")
			}
			return
		}
		switch msgType {
		case websocket.CloseMessage:
			_ = c.Close()
			return
		case websocket.BinaryMessage:
			outerMsg := MessageContainer{}
			err := json.Unmarshal(msg, &outerMsg)
			if err != nil {
				log.Warn().Err(err).Msg("Could not parse received WS message")
				_ = c.Close()
				return
			}

			switch outerMsg.MessageType {
			case MessageTypeRegisterClient:
				innerMsg := MessageRegisterClient{}
				err := json.Unmarshal(outerMsg.Data, &innerMsg)
				if err != nil {
					log.Warn().Err(err).Msg("Could not parse received registration message")
					_ = c.Close()
					return
				}

				response := MessageContainer{MessageType: MessageTypeRegisterClientOk}
				resData, err := json.Marshal(response)
				if err != nil {
					log.Fatal().Err(err).Msg("Could not marshal JSON response")
				}
				sendChan <- resData

				s.Clients[clientId] = wsClient{
					SendChan:           s.Clients[clientId].SendChan,
					RegisteredAsClient: &innerMsg.ClientName,
				}
			case MessageTypeClientStateUpdate:
				innerMsg := MessageClientStateUpdate{}
				err := json.Unmarshal(outerMsg.Data, &innerMsg)
				if err != nil {
					log.Warn().Err(err).Msg("Could not parse received client state update message")
					_ = c.Close()
					return
				}

				if s.Clients[clientId].RegisteredAsClient != nil {
					s.ClientStateUpdateListener(*s.Clients[clientId].RegisteredAsClient, innerMsg.State)
				}
			case MessageTypePeerSignal:
				innerMsg := MessagePeerSignal{}
				err := json.Unmarshal(outerMsg.Data, &innerMsg)
				if err != nil {
					log.Error().Err(err).Msg("Could not parse received peer signal message")
					_ = c.Close()
					return
				}
				for broadcastClientId, broadcastClient := range s.Clients {
					if broadcastClientId != clientId {
						// Forward peer signalling messages
						broadcastClient.SendChan <- msg
					}
				}
			case MessageTypeResults:
				s.writeResultsWaiter.Add(1)
				innerMsg := MessageResults{}
				err := json.Unmarshal(outerMsg.Data, &innerMsg)
				if err != nil {
					log.Error().Err(err).Msg("Could not parse received results message")
					_ = c.Close()
					return
				}

				client := s.Clients[clientId]
				cResultPath := s.currentResultPath
				resultFilePath := path.Join(cResultPath, *client.RegisteredAsClient+".parquet")
				metadataFilePath := path.Join(cResultPath, *client.RegisteredAsClient+"_meta.json")

				go func() {
					defer s.writeResultsWaiter.Done()
					resultsFile, err := os.Create(resultFilePath)
					if err != nil {
						log.Error().Err(err).Msgf("Could not open result file at %s", resultFilePath)
						return
					}
					defer resultsFile.Close()

					_, err = resultsFile.Write(innerMsg.FileData)
					if err != nil {
						log.Error().Err(err).Msgf("Could not write to result file")
						return
					}

					metadataFile, err := os.Create(metadataFilePath)
					if err != nil {
						log.Error().Err(err).Msgf("Could not open metadata file at %s", metadataFilePath)
						return
					}
					defer metadataFile.Close()

					metaBytes, err := json.Marshal(innerMsg.Metadata)
					if err != nil {
						log.Error().Err(err).Msg("Could not marshal JSON metadata message")
						return
					}

					_, err = metadataFile.Write(metaBytes)
					if err != nil {
						log.Error().Err(err).Msgf("Could not write to metadata file")
						return
					}

					if innerMsg.AdditionalFiles != nil {
						for name, data := range *innerMsg.AdditionalFiles {
							log.Debug().Msgf("Received extra result files %v with size %d", name, len(data))
							extraFile, err := os.Create(path.Join(cResultPath, name))
							if err != nil {
								log.Error().Err(err).Msgf("Could not create extra file at %s", path.Join(cResultPath, name))
								continue
							}
							_, err = extraFile.Write(data)
							if err != nil {
								log.Error().Err(err).Msgf("Could not write data to extra file at %s", path.Join(cResultPath, name))
							}
							_ = extraFile.Close()
						}
					}
				}()
			}
		}
	}
}

func (s *server) SetCurrentResultPath(path string) {
	s.currentResultPath = path
}
