package cases

import (
	"webrtc-bench/internal/cases/stats"
	"webrtc-bench/internal/util"
)

type CaseType string

const (
	CaseTypeConnect CaseType = "connect"
	CaseTypeVideo   CaseType = "video"
)

type Case struct {
	Name        string
	PeerConfigs map[string]PeerCaseConfig
	CaseType    CaseType
	Duration    util.JSONDuration
}

type PeerCaseExecutor interface {
	Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error, statCollector stats.StatCollector) error
	Start() error
	OnReceiveSignal(signalType PeerSignalType, message []byte) error
	Stop()
}

type PeerImplementation string

const (
	PeerImplementationPion   PeerImplementation = "pion"
	PeerImplementationChrome PeerImplementation = "chrome"
)

type PeerCaseConfig struct {
	Implementation   PeerImplementation
	ICEServers       []string
	SendOffer        bool
	StatInterval     util.JSONDuration
	AdditionalConfig map[string]string
}

type PeerSignalType string

const (
	PeerSignalTypeSDP        PeerSignalType = "sdp"
	PeerSignalTypeCandidates PeerSignalType = "candidates"
)

type FECType string

const (
	FECTypeDisabled FECType = "disabled"
	FECTypeFlexFEC  FECType = "flex"
	FECTypeULPFEC   FECType = "ulp"
)
