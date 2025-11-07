package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"io"
	"iter"
	"maps"
	"net/http"
	"os"
	"path"
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
	zerolog.SetGlobalLevel(zerolog.InfoLevel)

	caseFilePath := flag.String("cases", "cases.json", "path to cases configuration")
	resultsFolderPath := flag.String("results", "results", "path to results folder")
	authenticationKey := flag.String("key", "", "authentication key")
	bindAddress := flag.String("bind", "127.0.0.1:8080", "Bind to address")
	verbose := flag.Bool("v", false, "enable verbose mode")
	flag.Parse()

	if *verbose {
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
	}

	if authenticationKey == nil || *authenticationKey == "" {
		authKey := "default-auth-key"
		authenticationKey = &authKey
		log.Warn().Msg("Authentication key set to default!")
	}

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

	server := management.NewServer(*bindAddress, *authenticationKey)
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
					server.SetShuttingDown()
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
			caseIdentifier := fmt.Sprintf("%s-%s-%d", testCases[currentCase].CaseType, testCases[currentCase].Name, time.Now().Unix())
			resultsPath := path.Join(*resultsFolderPath, caseIdentifier)
			err = os.MkdirAll(resultsPath, os.ModePerm)
			if err != nil {
				log.Fatal().Err(err).Msg("Failed to create results folder")
				return
			}
			server.SetCurrentResultPath(resultsPath)

			caseFile, err := os.Create(path.Join(resultsPath, "case.json"))
			if err != nil {
				log.Fatal().Err(err).Msg("Failed to open case.json")
				return
			}

			caseData, err := json.Marshal(testCases[currentCase])
			if err != nil {
				log.Fatal().Err(err).Msg("Failed to marshal case for metadata storage")
				return
			}

			_, err = caseFile.Write(caseData)
			if err != nil {
				log.Fatal().Err(err).Msg("Failed to write case data to case.json")
				return
			}

			_ = caseFile.Close()

			if testCases[currentCase].ExternalDataSources != nil {
				log.Info().Msgf("Fetching external data source")
				for sourceName, sourceUrl := range *testCases[currentCase].ExternalDataSources {
					fetchExternalSource(path.Join(resultsPath, sourceName), sourceUrl)
				}
			}

			log.Info().Msg("Configuring clients")
			for name, peerConfig := range testCases[currentCase].PeerConfigs {
				err := server.SendMessage(name, management.MessageTypeConfigureClient, management.MessageConfigureClient{
					CaseType:     testCases[currentCase].CaseType,
					Config:       peerConfig,
					CaseDuration: testCases[currentCase].Duration,
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
				clientStateLock.Lock()
				defer clientStateLock.Unlock()
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

func fetchExternalSource(resultPath string, url string) {
	log.Info().Msgf("Fetching external source: %s", url)
	dataFile, err := os.Create(resultPath)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to open external source result file")
	}

	defer dataFile.Close()

	res, err := http.Get(url)
	if err != nil {
		log.Error().Err(err).Msgf("Failed to fetch external source: %s", url)
		_, err := dataFile.WriteString(err.Error())
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to write error to external source result file")
		}
		return
	}
	if res.StatusCode != 200 {
		log.Error().Msgf("Failed to fetch external source (Status %s [%d])", res.Status, res.StatusCode)
		_, err := dataFile.WriteString(fmt.Sprintf("Failed to fetch external source (Status %s [%d])", res.Status, res.StatusCode))
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to write status code error to external source result file")
		}
	}

	_, err = dataFile.ReadFrom(res.Body)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to write result to external source result file")
	}
	log.Info().Msgf("Successfully fetched external source: %s", url)
}
