package main

import (
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"os"
	"pion-bench/internal/cases"
	"pion-bench/internal/management"
	"time"
)

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout})

	server := management.NewServer(8080, "someAuthenticationKey")
	server.Start()

	connectedClients := 0
	server.SetRegisteredClientUpdateListener(func(isConnected bool, clientName string) {
		if isConnected {
			log.Info().Msgf("Client %s connected", clientName)
			connectedClients++
		} else {
			log.Info().Msgf("Client %s disconnected", clientName)
			connectedClients--
			return
		}

		if connectedClients == 2 {
			go startTestExec(server)
		}
	})

	select {}
}

func startTestExec(server management.Server) {
	testCase := cases.Case{
		PeerConfigs: map[string]cases.PeerCaseConfig{
			"starlink": {
				ICEServers:       []string{"stun:stun.l.google.com:19302"},
				SendOffer:        true,
				AdditionalConfig: nil,
			},
			"server": {
				ICEServers:       []string{"stun:stun.l.google.com:19302"},
				SendOffer:        false,
				AdditionalConfig: nil,
			},
		},
		Duration: time.Minute * 5,
	}

	log.Info().Msg("Configuring clients")
	for name, peerConfig := range testCase.PeerConfigs {
		err := server.SendMessage(name, management.MessageTypeConfigureClient, management.MessageConfigureClient{
			CaseType: cases.CaseTypeConnect,
			Config:   peerConfig,
		})
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to send configure client message")
			return
		}
	}

	log.Info().Msg("Starting test case")
	for name, _ := range testCase.PeerConfigs {
		err := server.SendMessage(name, management.MessageTypeStartCaseExecution, nil)
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to send start case execution message")
			return
		}
	}

	time.Sleep(testCase.Duration)

	log.Info().Msg("Stopping test case")
	for name, _ := range testCase.PeerConfigs {
		err := server.SendMessage(name, management.MessageTypeStopCaseExecution, nil)
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to send start case execution message")
			return
		}
	}
}
