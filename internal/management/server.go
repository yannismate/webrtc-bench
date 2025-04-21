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
	"strconv"
	"syscall"
	"time"
)

type Server interface {
	Start()
	SetRegisteredClientUpdateListener(func(bool, string))
	SendMessage(clientName string, messageType MessageType, content interface{}) error
}

type server struct {
	Port int
	// This is not particularly secure over non-HTTPS connections, but it will do for these benchmarks
	AuthenticationKey        string
	Clients                  map[string]wsClient
	OnRegisteredClientUpdate func(bool, string)
}

type wsClient struct {
	SendChan           chan []byte
	RegisteredAsClient *string
}

func NewServer(port int, authenticationKey string) Server {
	return &server{
		Port:                     port,
		AuthenticationKey:        authenticationKey,
		Clients:                  make(map[string]wsClient),
		OnRegisteredClientUpdate: func(bool, string) {},
	}
}

func (s *server) Start() {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleWs)

	httpServer := &http.Server{
		Addr:    ":" + strconv.Itoa(s.Port),
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
		log.Info().Msgf("Starting control server on port %d", s.Port)
		err := httpServer.ListenAndServe()
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatal().Err(err).Msg("HTTP server stopped unexpectedly")
		}
		os.Exit(0)
	}()
}

func (s *server) SetRegisteredClientUpdateListener(f func(bool, string)) {
	s.OnRegisteredClientUpdate = f
}

func (s *server) getPeerByName(name string) (wsClient, bool) {
	for _, client := range s.Clients {
		if client.RegisteredAsClient != nil && *client.RegisteredAsClient == name {
			return client, true
		}
	}
	return wsClient{}, false
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

	sendChan := make(chan []byte)
	s.Clients[clientId] = wsClient{
		SendChan: sendChan,
	}

	defer func() {
		_ = c.Close()
		disconnectedClient := s.Clients[clientId]
		if disconnectedClient.RegisteredAsClient != nil {
			log.Warn().Str("client_id", clientId).Str("client_name", *disconnectedClient.RegisteredAsClient).Msg("Registered client disconnected")
			s.OnRegisteredClientUpdate(false, *disconnectedClient.RegisteredAsClient)
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
				_ = c.SetWriteDeadline(time.Now().Add(time.Second * 3))
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
			log.Warn().Err(err).Msg("Could not read WS")
			return
		}
		switch msgType {
		case websocket.CloseMessage:
			_ = c.Close()
			return
		case websocket.PingMessage:
			_ = c.WriteMessage(websocket.PongMessage, nil)
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
				s.OnRegisteredClientUpdate(true, innerMsg.ClientName)
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
			}
		}
	}
}
