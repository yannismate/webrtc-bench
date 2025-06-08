package cases

import (
	"encoding/json"
	"errors"
	"github.com/pion/interceptor/pkg/flexfec"
	"github.com/pion/interceptor/pkg/report"
	"io"
	"os"
	"strconv"
	"sync"
	"time"
	"webrtc-bench/internal/cases/stats"
	"webrtc-bench/internal/cases/testsource"
	"webrtc-bench/internal/pion/scream"

	"github.com/pion/interceptor"
	"github.com/pion/interceptor/pkg/cc"
	"github.com/pion/interceptor/pkg/gcc"
	"github.com/pion/webrtc/v4"
	"github.com/rs/zerolog/log"
)

type CaseVideoPion struct {
	sendSignal            func(signalType PeerSignalType, data []byte) error
	webrtcCfg             webrtc.Configuration
	sendOffer             bool
	peerConnection        *webrtc.PeerConnection
	congestionControlType congestionControlType
	targetBitrate         int
	fecType               FECType
	transceiver           *webrtc.RTPTransceiver

	pendingCandidates []*webrtc.ICECandidate
	candidatesMux     sync.Mutex
	statCollector     stats.StatCollector
	statInterval      time.Duration
	testSource        testsource.FakeRTPDataWriter
}

type congestionControlType string

const (
	noCongestionControl     congestionControlType = "none"
	gccCongestionControl    congestionControlType = "gcc"
	screamCongestionControl congestionControlType = "scream"
)

func (c *CaseVideoPion) Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error, statCollector stats.StatCollector) error {
	c.sendSignal = sendSignal
	c.webrtcCfg = webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{
			{
				URLs: config.ICEServers,
			},
		},
	}
	c.sendOffer = config.SendOffer
	c.statCollector = statCollector

	bitrateStr, ok := config.AdditionalConfig["bitrate"]
	if !ok {
		bitrateStr = "10000"
	}
	bitrate, err := strconv.Atoi(bitrateStr)
	if err != nil {
		return err
	}
	c.targetBitrate = bitrate

	cct, ok := config.AdditionalConfig["congestion_control"]
	if ok {
		c.congestionControlType = congestionControlType(cct)
	} else {
		c.congestionControlType = noCongestionControl
	}

	fecTypeStr, ok := config.AdditionalConfig["fec"]
	if ok {
		c.fecType = FECType(fecTypeStr)
	} else {
		c.fecType = FECTypeDisabled
	}

	c.testSource = testsource.NewFakeRTPDataWriter(bitrate)
	return nil
}

func (c *CaseVideoPion) Start() error {
	mediaEngine := webrtc.MediaEngine{}
	settings := webrtc.SettingEngine{}

	if len(os.Getenv("EXPORT_DTLS_KEYS")) > 0 {
		file, err := os.OpenFile(os.Getenv("EXPORT_DTLS_KEYS"), os.O_RDWR|os.O_CREATE, 0666)
		if err != nil {
			return err
		}

		settings.SetDTLSKeyLogWriter(file)
	}

	videoRTCPFeedback := []webrtc.RTCPFeedback{{"goog-remb", ""}, {"ccm", "fir"}, {"nack", ""}, {"nack", "pli"}}
	codecParams := []webrtc.RTPCodecParameters{
		{
			RTPCodecCapability: webrtc.RTPCodecCapability{
				MimeType: webrtc.MimeTypeH264, ClockRate: 90000,
				SDPFmtpLine:  "level-asymmetry-allowed=1;packetization-mode=1",
				RTCPFeedback: videoRTCPFeedback,
			},
			PayloadType: 102,
		},
		{
			RTPCodecCapability: webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeRTX, ClockRate: 90000, SDPFmtpLine: "apt=102"},
			PayloadType:        103,
		},
	}
	for _, codec := range codecParams {
		if err := mediaEngine.RegisterCodec(codec, webrtc.RTPCodecTypeVideo); err != nil {
			return err
		}
	}
	icRegistry := interceptor.Registry{}

	if !c.sendOffer {
		// Configure receiver interceptors in order

		// 1. Stats
		icRegistry.Add(c.statCollector.GetPionInterceptorFactory())

		// 2. NACK
		if err := webrtc.ConfigureNack(&mediaEngine, &icRegistry); err != nil {
			return err
		}

		// 3. RR
		rr, err := report.NewReceiverInterceptor()
		if err != nil {
			return err
		}
		icRegistry.Add(rr)

		// 4. TWCC
		err = webrtc.ConfigureTWCCHeaderExtensionSender(&mediaEngine, &icRegistry)
		if err != nil {
			return err
		}

		// 5. CC
		switch c.congestionControlType {
		case noCongestionControl:
			log.Warn().Msg("Congestion control is set to none")
		case gccCongestionControl:
			err := webrtc.ConfigureTWCCSender(&mediaEngine, &icRegistry)
			if err != nil {
				return err
			}
		case screamCongestionControl:
			receiverInterceptor, err := scream.NewReceiverInterceptor()
			if err != nil {
				return err
			}

			icRegistry.Add(receiverInterceptor)
		default:
			log.Fatal().Msgf("invalid congestion control type: %s", c.congestionControlType)
		}

		// 6. FCC
		if c.fecType == FECTypeFlexFEC {
			flexFexInterceptor, err := flexfec.NewFecInterceptor()
			if err != nil {
				return err
			}
			icRegistry.Add(flexFexInterceptor)
		} else if c.fecType != FECTypeDisabled {
			log.Fatal().Msgf("Invalid FEC type for Pion: %s", c.fecType)
		}

	} else {
		// Configure sender interceptors in order
		// 1. SR
		sr, err := report.NewSenderInterceptor()
		if err != nil {
			return err
		}
		icRegistry.Add(sr)

		// 2. NACK
		if err := webrtc.ConfigureNack(&mediaEngine, &icRegistry); err != nil {
			return err
		}

		// 3. CC
		switch c.congestionControlType {
		case noCongestionControl:
			log.Warn().Msg("Congestion control is set to none")
		case gccCongestionControl:
			bwe, err := gcc.NewSendSideBWE(gcc.SendSideBWEInitialBitrate(c.targetBitrate/2),
				gcc.SendSideBWEMaxBitrate(c.targetBitrate*2))
			if err != nil {
				return err
			}
			bwe.OnTargetBitrateChange(func(bitrate int) {
				c.testSource.SetBitrate(min(bitrate, c.targetBitrate))
			})
			c.statCollector.AddGCCEstimatorCollection(bwe)

			ccFactory, err := cc.NewInterceptor(func() (cc.BandwidthEstimator, error) { return bwe, err })
			if err != nil {
				return err
			}
			icRegistry.Add(ccFactory)
		case screamCongestionControl:
			var bitrateUpdateNotifier = make(chan int)
			senderInterceptor, err := scream.NewSenderInterceptor(
				scream.MaxBitrate(float64(2*c.targetBitrate)),
				scream.InitialBitrate(float64(c.targetBitrate/2)),
				scream.TotalBitrateChangeNotifier(bitrateUpdateNotifier),
				scream.OnSenderInterceptorCreated(c.statCollector.AddScreamSenderCollection))

			go func() {
				for br := range bitrateUpdateNotifier {
					c.testSource.SetBitrate(min(br, c.targetBitrate))
				}
			}()

			if err != nil {
				return err
			}

			icRegistry.Add(senderInterceptor)
		default:
			log.Fatal().Msgf("invalid congestion control type: %s", c.congestionControlType)
		}

		// 4. TWCC
		err = webrtc.ConfigureTWCCHeaderExtensionSender(&mediaEngine, &icRegistry)
		if err != nil {
			return err
		}

		// 5. FCC
		if c.fecType == FECTypeFlexFEC {
			flexFexInterceptor, err := flexfec.NewFecInterceptor()
			if err != nil {
				return err
			}
			icRegistry.Add(flexFexInterceptor)
		} else if c.fecType != FECTypeDisabled {
			log.Fatal().Msgf("Invalid FEC type for Pion: %s", c.fecType)
		}

		// 6. Stats
		icRegistry.Add(c.statCollector.GetPionInterceptorFactory())
	}

	api := webrtc.NewAPI(webrtc.WithMediaEngine(&mediaEngine), webrtc.WithInterceptorRegistry(&icRegistry), webrtc.WithSettingEngine(settings))
	peerConnection, err := api.NewPeerConnection(c.webrtcCfg)
	c.peerConnection = peerConnection
	if err != nil {
		return err
	}

	peerConnection.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		log.Info().Msgf("Peer Connection State has changed: %s", state.String())
		if state == webrtc.PeerConnectionStateConnected {
			if c.sendOffer {
				c.statCollector.StartCollection(c.testSource.Start())
			}
		} else if state == webrtc.PeerConnectionStateDisconnected {
			if c.sendOffer {
				c.testSource.Stop()
			}
			c.statCollector.StopCollection()
		}
	})

	peerConnection.OnICECandidate(func(candidate *webrtc.ICECandidate) {
		if candidate == nil {
			return
		}

		c.candidatesMux.Lock()
		defer c.candidatesMux.Unlock()

		desc := peerConnection.RemoteDescription()
		if desc == nil {
			c.pendingCandidates = append(c.pendingCandidates, candidate)
		}
		err := c.sendCandidate(candidate)
		if err != nil {
			log.Error().Err(err).Msg("Failed to send candidate")
		}
	})

	peerConnection.OnTrack(func(remoteTrack *webrtc.TrackRemote, receiver *webrtc.RTPReceiver) {
		log.Info().Msgf("Received Track on SSRC %v with RTX SSRC %v", remoteTrack.SSRC(), remoteTrack.RtxSSRC())
		c.statCollector.StartCollection(uint32(remoteTrack.SSRC()), uint32(remoteTrack.RtxSSRC()))

		for {
			// read and discard RTP stream
			_, _, readErr := remoteTrack.ReadRTP()
			if readErr != nil {
				if readErr != io.EOF {
					log.Error().Err(readErr).Msgf("Error reading from remote track")
				}
				_ = peerConnection.Close()
				break
			}
		}
	})

	if c.sendOffer {
		transceiver, err := peerConnection.AddTransceiverFromKind(webrtc.RTPCodecTypeVideo, webrtc.RTPTransceiverInit{Direction: webrtc.RTPTransceiverDirectionSendonly})
		if err != nil {
			return err
		}
		c.transceiver = transceiver

		err = c.testSource.CreateTrack(transceiver)
		if err != nil {
			log.Error().Err(err).Msg("Failed to create RTP track")
			return err
		}

		offer, err := peerConnection.CreateOffer(nil)
		if err != nil {
			log.Error().Err(err).Msg("Failed to create SDP offer")
			return err
		}

		err = peerConnection.SetLocalDescription(offer)
		if err != nil {
			log.Error().Err(err).Msg("Failed to set local SDP")
			return err
		}

		offerPayload, err := json.Marshal(offer)
		if err != nil {
			log.Error().Err(err).Msg("Failed to marshal offer")
			return err
		}

		err = c.sendSignal(PeerSignalTypeSDP, offerPayload)
		if err != nil {
			log.Error().Err(err).Msg("Failed to send offer")
			return err
		}
	} else {
		transceiver, err := peerConnection.AddTransceiverFromKind(webrtc.RTPCodecTypeVideo, webrtc.RTPTransceiverInit{Direction: webrtc.RTPTransceiverDirectionRecvonly})
		if err != nil {
			return err
		}
		c.transceiver = transceiver
	}

	return c.transceiver.SetCodecPreferences(codecParams)
}

func (c *CaseVideoPion) OnReceiveSignal(signalType PeerSignalType, message []byte) error {
	log.Debug().Msgf("OnReceiveSignal: [%s] %s", signalType, message)
	if signalType == PeerSignalTypeSDP {
		sdp := webrtc.SessionDescription{}
		err := json.Unmarshal(message, &sdp)
		if err != nil {
			log.Error().Err(err).Msg("Failed to unmarshal signalled SDP")
			return err
		}

		err = c.peerConnection.SetRemoteDescription(sdp)
		if err != nil {
			log.Error().Err(err).Msg("Failed to set remote SDP")
			return err
		}

		if sdp.Type == webrtc.SDPTypeAnswer {
			for _, cand := range c.pendingCandidates {
				err := c.sendCandidate(cand)
				if err != nil {
					log.Error().Err(err).Msg("Failed to send candidate")
					return err
				}
			}
			return nil
		}

		answer, err := c.peerConnection.CreateAnswer(nil)
		if err != nil {
			log.Error().Err(err).Msg("Failed to create SDP answer")
			return err
		}

		answerPayload, err := json.Marshal(answer)
		if err != nil {
			log.Error().Err(err).Msg("Failed to marshal SDP answer")
			return err
		}

		err = c.sendSignal(PeerSignalTypeSDP, answerPayload)
		if err != nil {
			log.Error().Err(err).Msg("Failed to send SDP answer")
			return err
		}

		err = c.peerConnection.SetLocalDescription(answer)
		if err != nil {
			log.Error().Err(err).Msg("Failed to set local SDP")
			return err
		}

		for _, cand := range c.pendingCandidates {
			err := c.sendCandidate(cand)
			if err != nil {
				log.Error().Err(err).Msg("Failed to send candidate")
				return err
			}
		}
		return nil
	} else if signalType == PeerSignalTypeCandidates {
		if c.peerConnection.RemoteDescription() == nil {
			return nil
		}
		candidate := webrtc.ICECandidateInit{}
		err := json.Unmarshal(message, &candidate)
		if err != nil {
			log.Error().Err(err).Msg("Failed to unmarshal candidate")
			return err
		}

		err = c.peerConnection.AddICECandidate(candidate)
		if err != nil {
			log.Error().Err(err).Msg("Failed to add received ICECandidate")
			return err
		}
		return nil
	}
	return errors.New("unrecognized signalType")
}

func (c *CaseVideoPion) sendCandidate(cand *webrtc.ICECandidate) error {
	payload, err := json.Marshal(cand.ToJSON())
	if err != nil {
		log.Error().Err(err).Msg("Failed to marshal candidate")
	}
	err = c.sendSignal(PeerSignalTypeCandidates, payload)
	if err != nil {
		log.Error().Err(err).Msgf("Error sending candidates signal")
	}

	return nil
}

func (c *CaseVideoPion) Stop() {
	c.statCollector.StopCollection()
	_ = c.peerConnection.Close()
}
