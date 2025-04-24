package cases

import (
	"webrtc-bench/internal/util"
)

type CaseType string

const (
	CaseTypeConnect CaseType = "connect"
)

type Case struct {
	Name        string
	PeerConfigs map[string]PeerCaseConfig
	CaseType    CaseType
	Duration    util.JSONDuration
}

type PeerCaseExecutor interface {
	Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error) error
	Start() error
	OnReceiveSignal(signalType PeerSignalType, message []byte) error
	Stop()
}

type PeerCaseConfig struct {
	ICEServers       []string
	SendOffer        bool
	AdditionalConfig map[string]string
}

type PeerSignalType string

const (
	PeerSignalTypeSDP        PeerSignalType = "sdp"
	PeerSignalTypeCandidates PeerSignalType = "candidates"
)
