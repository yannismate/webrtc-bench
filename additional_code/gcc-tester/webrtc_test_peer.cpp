#include "webrtc_test_peer.h"
#include <chrono>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "api/safe_ostream.h"
#include "api/audio_codecs/builtin_audio_decoder_factory.h"
#include "api/audio_codecs/builtin_audio_encoder_factory.h"
#include "api/video_codecs/video_decoder_factory_template.h"
#include "api/video_codecs/video_decoder_factory_template_libvpx_vp8_adapter.h"
#include "api/video_codecs/video_encoder_factory_template.h"
#include "api/video_codecs/video_encoder_factory_template_libvpx_vp8_adapter.h"
#include "api/create_peerconnection_factory.h"
#include "api/peer_connection_interface.h"
#include "fake_track_source.h"
#include "ffmpeg_receiver_sink.h"
#include "h264_only_factory.h"
#include "syncodec_decoder_factory.h"
#include "syncodec_encoder_factory.h"

static auto g_signal_thread = webrtc::Thread::Create();
static auto g_stat_thread = webrtc::Thread::Create();

WebRTCTestPeer::WebRTCTestPeer(const bool is_sender, const int target_bitrate, const int target_fps,
                               const std::vector<std::string> &ice_servers, int stat_interval_ms,
                               std::string use_real_codec, bool use_ffmpeg_source,
                               std::string ffmpeg_source_file, bool use_ffmpeg_output,
                               std::optional<int> min_jitter_buffer_ms, std::string field_trials) {
    is_sender_ = is_sender;
    target_bitrate_ = target_bitrate;
    target_fps_ = target_fps;
    ice_servers_ = ice_servers;
    stat_interval_ms_ = stat_interval_ms;
    use_real_codec_ = std::move(use_real_codec);
    use_ffmpeg_source_ = use_ffmpeg_source;
    ffmpeg_source_file_ = std::move(ffmpeg_source_file);
    use_ffmpeg_output_ = use_ffmpeg_output;
    min_jitter_buffer_ms_ = min_jitter_buffer_ms;
    field_trials_ = std::move(field_trials);
}

WebRTCTestPeer::~WebRTCTestPeer() {
    if (peer_connection_) {
        peer_connection_->Close();
        peer_connection_ = nullptr;
    }
    std::cout << "WebRTCTestPeer destroyed." << std::endl;
}

void WebRTCTestPeer::Start() {
    auto config = webrtc::PeerConnectionInterface::RTCConfiguration();
    for (const auto &server: ice_servers_) {
        webrtc::PeerConnectionInterface::IceServer ice_server;
        ice_server.urls.push_back(server);
        if (server.find("turn:") == 0) {
            ice_server.username = "user1";
            ice_server.password = "LjxsJzriFcrwtqDBdYJ";
        }
        config.servers.push_back(ice_server);
    }

    g_signal_thread->SetName("webrtc_signal", nullptr);
    g_signal_thread->Start();

    g_stat_thread->Start();

    g_signal_thread->BlockingCall([this, config] {
        auto field_trials = std::make_unique<CustomFieldTrialsView>(field_trials_);

        std::unique_ptr<webrtc::VideoEncoderFactory> video_encoder_factory = nullptr;
        std::unique_ptr<webrtc::VideoDecoderFactory> video_decoder_factory = nullptr;

        if (use_real_codec_.empty()) {
            std::cout << "Using synthetic codec." << std::endl;
            video_encoder_factory = std::make_unique<syncodecs::SynCodecsVideoEncoderFactory>(target_fps_);
            video_decoder_factory = std::make_unique<syncodecs::SynCodecsVideoDecoderFactory>();
        } else if (use_real_codec_ == "h264") {
            std::cout << "Using OpenH264." << std::endl;
            video_encoder_factory = std::make_unique<H264OnlyVideoEncoderFactory>();
            video_decoder_factory = std::make_unique<H264OnlyVideoDecoderFactory>();
        } else if (use_real_codec_ == "vp8") {
            std::cout << "Using VP8." << std::endl;
            video_encoder_factory = std::make_unique<webrtc::VideoEncoderFactoryTemplate<webrtc::LibvpxVp8EncoderTemplateAdapter>>();
            video_decoder_factory = std::make_unique<webrtc::VideoDecoderFactoryTemplate<webrtc::LibvpxVp8DecoderTemplateAdapter>>();
        } else {
            std::cerr << "Unknown codec specified: " << use_real_codec_ << std::endl;
            return;
        }

        auto factory = webrtc::CreatePeerConnectionFactory(
                nullptr, nullptr, g_signal_thread.get(), nullptr, webrtc::CreateBuiltinAudioEncoderFactory(),
                webrtc::CreateBuiltinAudioDecoderFactory(), std::move(video_encoder_factory),
                std::move(video_decoder_factory), nullptr, nullptr, nullptr, std::move(field_trials));

        auto observer = std::make_unique<WebRTCObserver>(shared_from_this(), use_ffmpeg_output_, min_jitter_buffer_ms_);

        auto peer_connection_res =
                factory->CreatePeerConnectionOrError(config, webrtc::PeerConnectionDependencies(observer.release()));
        if (!peer_connection_res.ok()) {
            std::cerr << "Failed to create PeerConnection: " << peer_connection_res.error().message() << std::endl;
            return;
        }
        peer_connection_ = peer_connection_res.value();

        std::cout << "PeerConnection created successfully." << std::endl;

        sdp_observer_ = webrtc::make_ref_counted<WebRTCSDPGenerateObserver>(shared_from_this());

        if (is_sender_) {
            auto source_type = BLACK;
            if (!use_real_codec_.empty()) {
                if (use_ffmpeg_source_) {
                    source_type = FFMPEG;
                } else {
                    source_type = RANDOM_NOISE;
                }
            }
            fake_video_source_ = webrtc::make_ref_counted<FakeVideoSource>(source_type, ffmpeg_source_file_);
            auto track = factory->CreateVideoTrack(fake_video_source_, "fake_video");

            auto transceiver_res = peer_connection_->AddTransceiver(track);
            if (!transceiver_res.ok()) {
                std::cerr << "Failed to add transceiver: " << transceiver_res.error().message() << std::endl;
                return;
            }
            auto transceiver = transceiver_res.MoveValue();

            auto sender = transceiver->sender();
            auto params = sender->GetParameters();
            if (params.encodings.empty()) {
                params.encodings.emplace_back();
            }
            params.encodings[0].max_bitrate_bps = target_bitrate_;
            params.encodings[0].max_framerate = target_fps_;
            params.degradation_preference = webrtc::DegradationPreference::MAINTAIN_RESOLUTION;
            sender->SetParameters(params);

            std::cout << "Creating offer..." << std::endl;
            peer_connection_->CreateOffer(sdp_observer_.get(),
                                          webrtc::PeerConnectionInterface::RTCOfferAnswerOptions());
        }

        g_stat_thread->PostTask([this] {
            auto observer = webrtc::make_ref_counted<WebRTCStatsCollectorCallback>();
            auto observer_ptr = observer.release();
            while (this->peer_connection_ != nullptr) {
                this->peer_connection_->GetStats(observer_ptr);
                std::this_thread::sleep_for(std::chrono::milliseconds(stat_interval_ms_));
            }
        });
    });
}

void WebRTCTestPeer::Stop() {
    if (fake_video_source_) {
        fake_video_source_->StopSource();
        fake_video_source_ = nullptr;
    }
    if (peer_connection_) {
        peer_connection_->Close();
        peer_connection_ = nullptr;
    }
    if (ffmpeg_sink) {
        ffmpeg_sink->Stop();
        ffmpeg_sink = nullptr;
    }
    g_signal_thread->Stop();
    g_stat_thread->Stop();
    std::cout << "WebRTCTestPeer stopped." << std::endl;
}

void WebRTCTestPeer::SetLocalSDP(webrtc::SessionDescriptionInterface *desc) const {
    std::cout << "Setting local SDP with type " << desc->type() << std::endl;
    auto sdp_set_observer = webrtc::make_ref_counted<WebRTCLocalSDPObserver>();
    peer_connection_->SetLocalDescription(std::unique_ptr<webrtc::SessionDescriptionInterface>(desc), sdp_set_observer);
}

void WebRTCTestPeer::ReceiveSDP(webrtc::SessionDescriptionInterface *desc) {
    std::cout << "Received remote SDP of type " << desc->type() << std::endl;
    auto sdp_set_remote_observer = webrtc::make_ref_counted<WebRTCRemoteSDPObserver>(shared_from_this());
    peer_connection_->SetRemoteDescription(std::unique_ptr<webrtc::SessionDescriptionInterface>(desc),
                                           sdp_set_remote_observer);
    if (desc->type() == webrtc::SessionDescriptionInterface::kOffer) {
        peer_connection_->CreateAnswer(sdp_observer_.get(), webrtc::PeerConnectionInterface::RTCOfferAnswerOptions());
    } else {
        fake_video_source_->StartSource(target_fps_);
    }
}

void WebRTCTestPeer::ReceiveICECandidate(webrtc::IceCandidate *candidate) {
    if (candidate == nullptr) {
        std::cout << "Received null candidate." << std::endl;
    }
    if (!remote_description_set_) {
        // Queue the candidate until remote description is applied.
        if (candidate) {
            PendingIceCandidate pending{};
            pending.sdp_mid = candidate->sdp_mid();
            pending.sdp_mline_index = candidate->sdp_mline_index();
            pending.candidate_sdp = candidate->ToString();
            pending_ice_candidates_.push_back(std::move(pending));
            std::cout << "Queued ICE candidate (mid=" << candidate->sdp_mid() << ", index="
                      << candidate->sdp_mline_index() << ") until remote description is set." << std::endl;
        }
        return;
    }
    std::cout << "Adding received ICE candidate (mid=" << candidate->sdp_mid() << ", index="
              << candidate->sdp_mline_index() << ")." << std::endl;
    peer_connection_->AddIceCandidate(candidate);
}

void WebRTCTestPeer::OnRemoteDescriptionApplied(bool success) {
    if (!success) {
        std::cout << "Remote description failed to apply; pending ICE candidates will be discarded." << std::endl;
        pending_ice_candidates_.clear();
        return;
    }
    remote_description_set_ = true;
    FlushPendingIceCandidates();
}

void WebRTCTestPeer::FlushPendingIceCandidates() {
    if (pending_ice_candidates_.empty()) return;

    std::cout << "Flushing " << pending_ice_candidates_.size() << " queued ICE candidate(s)." << std::endl;
    for (const auto &pending : pending_ice_candidates_) {
        webrtc::SdpParseError parse_error;
        webrtc::IceCandidateInterface* raw = webrtc::CreateIceCandidate(
                pending.sdp_mid, pending.sdp_mline_index, pending.candidate_sdp, &parse_error);
        std::unique_ptr<webrtc::IceCandidateInterface> ice(raw);
        if (!ice) {
            std::cout << "Failed to recreate ICE candidate from queued data: " << parse_error.description << std::endl;
            continue;
        }
        if (!peer_connection_->AddIceCandidate(ice.get())) {
            std::cout << "Failed to add queued ICE candidate (mid=" << pending.sdp_mid << ")" << std::endl;
        }
    }
    pending_ice_candidates_.clear();
}

WebRTCObserver::WebRTCObserver(std::shared_ptr<WebRTCTestPeer> tp, bool use_ffmpeg_output, std::optional<int> min_jitter_buffer_ms) :
    tp_(std::move(tp)), use_ffmpeg_output_(use_ffmpeg_output), min_jitter_buffer_ms_(min_jitter_buffer_ms) {}

void WebRTCObserver::OnConnectionChange(webrtc::PeerConnectionInterface::PeerConnectionState new_state) {
    std::cout << "PeerConnection changed: " << webrtc::PeerConnectionInterface::AsString(new_state) << std::endl;
}

void WebRTCObserver::OnSignalingChange(webrtc::PeerConnectionInterface::SignalingState new_state) {
    std::cout << "Signaling change: " << webrtc::PeerConnectionInterface::AsString(new_state) << std::endl;
}

void WebRTCObserver::OnDataChannel(webrtc::scoped_refptr<webrtc::DataChannelInterface> data_channel) {
    std::cout << "Data channel created: " << data_channel->label() << std::endl;
}

void WebRTCObserver::OnIceGatheringChange(webrtc::PeerConnectionInterface::IceGatheringState new_state) {
    std::cout << "ICE gathering change: " << webrtc::PeerConnectionInterface::AsString(new_state) << std::endl;
}

void WebRTCObserver::OnIceCandidate(const webrtc::IceCandidate *candidate) {
    if (candidate) {
        std::cout << "New ICE candidate: " << candidate->sdp_mid() << " " << candidate->sdp_mline_index() << std::endl;
        auto cand_str = candidate->ToString();
        std::cout << "SIGNAL/SDP/candidate/" << cand_str << std::endl;
    } else {
        std::cout << "All ICE candidates have been gathered." << std::endl;
    }
}

void WebRTCObserver::OnTrack(webrtc::scoped_refptr<webrtc::RtpTransceiverInterface> transceiver) {
    if (!use_ffmpeg_output_) {
        std::cout << "FFmpeg output disabled, skipping track processing." << std::endl;
        return;
    }
    std::cout << "Track received: " << transceiver->receiver()->track()->id() << ", starting ffmpeg output!"
              << std::endl;
    if (auto track = transceiver->receiver()->track()) {
        if (track && track->kind() == webrtc::MediaStreamTrackInterface::kVideoKind) {
            auto video_track = dynamic_cast<webrtc::VideoTrackInterface *>(track.get());
            auto sink = std::make_unique<FFMpegReceiverSink>();
            sink->Start();
            auto sink_ptr = sink.release();
            tp_->ffmpeg_sink = sink_ptr;
            video_track->AddOrUpdateSink(sink_ptr, webrtc::VideoSinkWants());
            if (min_jitter_buffer_ms_ != std::nullopt) {
                double millis = (min_jitter_buffer_ms_.value() * 1.0) / 1000.0;
                transceiver->receiver()->SetJitterBufferMinimumDelay(millis);
                webrtc::safe_cout() << "Manually set jitter buffer min delay.\n";
            }
        }
    }
}

WebRTCSDPGenerateObserver::WebRTCSDPGenerateObserver(std::shared_ptr<WebRTCTestPeer> tp) : tp_(std::move(tp)) {}

void WebRTCSDPGenerateObserver::OnSuccess(webrtc::SessionDescriptionInterface *desc) {
    tp_->SetLocalSDP(desc);
    std::cout << "Session description created successfully: " << desc->type() << std::endl;
    std::string sdp_string;
    std::string escaped;
    desc->ToString(&sdp_string);
    for (char c: sdp_string) {
        if (c == '\r')
            escaped += "\\r";
        else if (c == '\n')
            escaped += "\\n";
        else
            escaped += c;
    }
    auto type = desc->type() == webrtc::SessionDescriptionInterface::kOffer ? "offer" : "answer";
    std::cout << "SIGNAL/SDP/" << type << "/" << escaped << std::endl;
}


void WebRTCSDPGenerateObserver::OnFailure(webrtc::RTCError error) {
    if (!error.ok()) {
        std::cout << "Error callback: " << error.message() << std::endl;
    }
}

void WebRTCLocalSDPObserver::OnSetLocalDescriptionComplete(webrtc::RTCError error) {
    if (!error.ok()) {
        std::cout << "Error callback: " << error.message() << std::endl;
    } else {
        std::cout << "Local SDP set." << std::endl;
    }
}

void WebRTCRemoteSDPObserver::OnSetRemoteDescriptionComplete(webrtc::RTCError error) {
    if (!error.ok()) {
        std::cout << "Error callback: " << error.message() << std::endl;
        tp_->OnRemoteDescriptionApplied(false);
    } else {
        std::cout << "Remote SDP set." << std::endl;
        tp_->OnRemoteDescriptionApplied(true);
    }
}

void WebRTCStatsCollectorCallback::OnStatsDelivered(const webrtc::scoped_refptr<const webrtc::RTCStatsReport> &report) {
    if (!report) {
        std::cout << "Stats report is null." << std::endl;
        return;
    }

    std::string stats_output = "SIGNAL/STATS/[";
    for (const auto &stat: *report) {
        std::string stat_type = stat.type();
        if (stat_type.find("rtp") == std::string::npos) {
            continue;
        }
        if (stats_output.size() > 14) {
            stats_output += ", ";
        }
        stats_output += stat.ToJson();
    }
    stats_output += "]\n";
    webrtc::safe_cout() << stats_output;
}
