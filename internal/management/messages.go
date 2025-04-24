package management

import (
	"encoding/json"
	"webrtc-bench/internal/cases"
)

const (
	AuthenticationKeyHeader = "X-Api-Key"
)

type MessageType string

const (
	MessageTypeRegisterClient     MessageType = "register_client"
	MessageTypeRegisterClientOk   MessageType = "register_client_ok"
	MessageTypeClientStateUpdate  MessageType = "client_state_update"
	MessageTypeConfigureClient    MessageType = "configure_client"
	MessageTypeStartCaseExecution MessageType = "start_case_execution"
	MessageTypeStopCaseExecution  MessageType = "stop_case_execution"
	MessageTypePeerSignal         MessageType = "peer_signal"
)

type MessageContainer struct {
	MessageType MessageType
	Data        json.RawMessage `json:"data,omitempty"`
}

type MessageRegisterClient struct {
	ClientName string
}

type ClientState string

const (
	ClientStateRegistered   ClientState = "registered"
	ClientStateConfiguring  ClientState = "configuring"
	ClientStateTestReady    ClientState = "test_ready"
	ClientStateTesting      ClientState = "testing"
	ClientStateTestEnding   ClientState = "test_ending"
	ClientStateFailure      ClientState = "failure"
	ClientStateDisconnected ClientState = "disconnected"
)

type MessageClientStateUpdate struct {
	State ClientState
}

type MessageConfigureClient struct {
	CaseType cases.CaseType
	Config   cases.PeerCaseConfig
}

type MessagePeerSignal struct {
	SignalType cases.PeerSignalType
	Data       []byte
}
