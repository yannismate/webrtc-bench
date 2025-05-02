package main

import (
	"encoding/json"
	"flag"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"io"
	"iter"
	"maps"
	"os"
	"sync"
	"time"
	"webrtc-bench/internal/cases"
	"webrtc-bench/internal/management"
)

type RunState int

const (
	RunStateBeforeTest RunState = iota
	RunStateTesting
	RunStateAfterTest
)

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout})

	caseFilePath := flag.String("cases", "cases.json", "path to cases configuration")
	flag.Parse()

	caseFile, err := os.Open(*caseFilePath)
	if err != nil {
		log.Fatal().Err(err).Str("path", *caseFilePath).Msg("Failed to open cases file")
		return
	}

	caseData, err := io.ReadAll(caseFile)
	if err != nil {
		log.Fatal().Err(err).Str("path", *caseFilePath).Msg("Failed to read cases file")
		return
	}
	_ = caseFile.Close()

	var testCases []cases.Case
	err = json.Unmarshal(caseData, &testCases)
	if err != nil {
		log.Fatal().Err(err).Str("path", *caseFilePath).Msg("Failed to parse cases file")
		return
	}

	server := management.NewServer("127.0.0.1:8080", "someAuthenticationKey")
	server.Start()

	connectedClients := make(map[string]management.ClientState)
	clientStateLock := &sync.Mutex{}
	currentCase := 0
	runState := RunStateBeforeTest
	endTestingChan := make(chan bool)

	server.SetClientStateUpdateListener(func(clientName string, newState management.ClientState) {
		clientStateLock.Lock()
		defer clientStateLock.Unlock()
		connectedClients[clientName] = newState
		log.Debug().Msgf("Client %s is now in state %s", clientName, newState)

		if (runState == RunStateBeforeTest || runState == RunStateAfterTest) &&
			allTestClientsInState(connectedClients, maps.Keys(testCases[currentCase].PeerConfigs), management.ClientStateRegistered) {

			if runState == RunStateAfterTest {
				if currentCase == len(testCases)-1 {
					log.Info().Msgf("Finished last test case! Shutting down clients.")
					for cn, _ := range connectedClients {
						_ = server.SendMessage(cn, management.MessageTypeShutdown, nil)
					}
					// Wait for shutdown commands to be sent
					time.Sleep(1 * time.Second)
					endTestingChan <- true
					return
				}
				runState = RunStateBeforeTest
				currentCase++
			}
			log.Info().Msg("Configuring clients")
			for name, peerConfig := range testCases[currentCase].PeerConfigs {
				err := server.SendMessage(name, management.MessageTypeConfigureClient, management.MessageConfigureClient{
					CaseType: testCases[currentCase].CaseType,
					Config:   peerConfig,
				})
				if err != nil {
					log.Fatal().Err(err).Msg("Failed to send configure client message")
					return
				}
			}
		} else if runState == RunStateBeforeTest &&
			allTestClientsInState(connectedClients, maps.Keys(testCases[currentCase].PeerConfigs), management.ClientStateTestReady) {

			log.Info().Msgf("Starting test case %s [%s]", testCases[currentCase].Name, testCases[currentCase].CaseType)
			runState = RunStateTesting
			for name, _ := range testCases[currentCase].PeerConfigs {
				err := server.SendMessage(name, management.MessageTypeStartCaseExecution, nil)
				if err != nil {
					log.Fatal().Err(err).Msg("Failed to send start case execution message")
					return
				}
			}
			go func() {
				time.Sleep(time.Duration(testCases[currentCase].Duration))
				runState = RunStateAfterTest
				log.Info().Msg("Stopping test case")
				for name, _ := range testCases[currentCase].PeerConfigs {
					err := server.SendMessage(name, management.MessageTypeStopCaseExecution, nil)
					if err != nil {
						log.Fatal().Err(err).Msg("Failed to send start case execution message")
						return
					}
				}
			}()
		} else if runState == RunStateTesting && newState != management.ClientStateTesting {
			log.Error().Msg("Client changed state during test!")
		}
	})

	select {
	case <-endTestingChan:
	}
}

func allTestClientsInState(states map[string]management.ClientState, requiredClients iter.Seq[string], requiredState management.ClientState) bool {
	for clientName := range requiredClients {
		if cState, ok := states[clientName]; ok {
			if cState != requiredState {
				return false
			}
		} else {
			return false
		}
	}
	return true
}
