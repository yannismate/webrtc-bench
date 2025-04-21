package management

import (
	"encoding/json"
	"pion-bench/internal/cases"
)

const (
	AuthenticationKeyHeader = "X-Api-Key"
)

type MessageType string

const (
	MessageTypeRegisterClient     MessageType = "register_client"
	MessageTypeRegisterClientOk   MessageType = "register_client_ok"
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

type MessageConfigureClient struct {
	CaseType cases.CaseType
	Config   cases.PeerCaseConfig
}

type MessagePeerSignal struct {
	SignalType cases.PeerSignalType
	Data       []byte
}
