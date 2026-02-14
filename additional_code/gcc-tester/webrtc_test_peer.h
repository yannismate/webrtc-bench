#ifndef WEBRTC_TEST_PEER_H
#define WEBRTC_TEST_PEER_H

#include <chrono>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "fake_track_source.h"
#include "ffmpeg_receiver_sink.h"
#include "api/peer_connection_interface.h"

class WebRTCSDPGenerateObserver;

class WebRTCTestPeer : public std::enable_shared_from_this<WebRTCTestPeer> {
public:
    WebRTCTestPeer(bool is_sender, int target_bitrate, int target_fps, const std::vector<std::string> &ice_servers,
        int stat_interval_ms, std::string use_real_codec, bool use_ffmpeg_source, std::string ffmpeg_source_file,
        bool use_ffmpeg_output, std::optional<int> min_jitter_buffer_ms, std::string field_trials);
    ~WebRTCTestPeer();
    void Start();
    void Stop();
    void SetLocalSDP(webrtc::SessionDescriptionInterface *desc) const;
    // Remote SDP / ICE handling (non-const because we mutate internal state / queues)
    void ReceiveSDP(webrtc::SessionDescriptionInterface* desc);
    void ReceiveICECandidate(webrtc::IceCandidate* desc);
    // Called by the remote SDP observer when the remote description has been applied successfully.
    void OnRemoteDescriptionApplied(bool success);
    FFMpegReceiverSink* ffmpeg_sink = nullptr;
private:
    struct PendingIceCandidate {
        std::string sdp_mid;
        int sdp_mline_index;
        std::string candidate_sdp; // The candidate attribute string
    };
    void FlushPendingIceCandidates();

    bool is_sender_;
    int target_bitrate_;
    int target_fps_;
    std::vector<std::string> ice_servers_;
    int stat_interval_ms_;
    std::string use_real_codec_;
    bool use_ffmpeg_source_;
    bool use_ffmpeg_output_;
    std::string ffmpeg_source_file_;
    std::optional<int> min_jitter_buffer_ms_;
    std::string field_trials_;
    webrtc::scoped_refptr<webrtc::PeerConnectionInterface> peer_connection_;
    webrtc::scoped_refptr<WebRTCSDPGenerateObserver> sdp_observer_;
    webrtc::scoped_refptr<FakeVideoSource> fake_video_source_;
    bool remote_description_set_ = false;
    std::vector<PendingIceCandidate> pending_ice_candidates_;
};

class WebRTCObserver : public webrtc::PeerConnectionObserver {
public:
    explicit WebRTCObserver(std::shared_ptr<WebRTCTestPeer> tp, bool use_ffmpeg_output, std::optional<int> min_jitter_buffer_ms);
    void OnSignalingChange(webrtc::PeerConnectionInterface::SignalingState new_state) override;
    void OnDataChannel(webrtc::scoped_refptr<webrtc::DataChannelInterface> data_channel) override;
    void OnIceGatheringChange(webrtc::PeerConnectionInterface::IceGatheringState new_state) override;
    void OnIceCandidate(const webrtc::IceCandidate *candidate) override;
    void OnConnectionChange(webrtc::PeerConnectionInterface::PeerConnectionState new_state) override;
    void OnTrack(webrtc::scoped_refptr<webrtc::RtpTransceiverInterface> transceiver) override;
private:
    const std::shared_ptr<WebRTCTestPeer> tp_;
    bool use_ffmpeg_output_;
    std::optional<int> min_jitter_buffer_ms_;
};

class WebRTCSDPGenerateObserver : public webrtc::CreateSessionDescriptionObserver {
public:
    explicit WebRTCSDPGenerateObserver(std::shared_ptr<WebRTCTestPeer> tp);
    void OnSuccess(webrtc::SessionDescriptionInterface* desc) override;
    void OnFailure(webrtc::RTCError error) override;
private:
    const std::shared_ptr<WebRTCTestPeer> tp_;
};

class WebRTCLocalSDPObserver : public webrtc::SetLocalDescriptionObserverInterface {
public:
    void OnSetLocalDescriptionComplete(webrtc::RTCError error) override;
};

class WebRTCRemoteSDPObserver : public webrtc::SetRemoteDescriptionObserverInterface {
public:
    explicit WebRTCRemoteSDPObserver(std::shared_ptr<WebRTCTestPeer> tp) : tp_(tp) {}
    void OnSetRemoteDescriptionComplete(webrtc::RTCError error) override;
private:
    const std::shared_ptr<WebRTCTestPeer> tp_;
};

class WebRTCStatsCollectorCallback : public webrtc::RTCStatsCollectorCallback {
public:
    WebRTCStatsCollectorCallback() = default;
    void OnStatsDelivered(const webrtc::scoped_refptr<const webrtc::RTCStatsReport>& report) override;
};

class CustomFieldTrialsView : public webrtc::FieldTrialsView {
public:
    explicit CustomFieldTrialsView(const std::string& field_trials_string) {
        ParseFieldTrials(field_trials_string);
    }
    
    [[nodiscard]] std::string Lookup(absl::string_view key) const override {
        auto it = trials_.find(std::string(key));
        if (it != trials_.end()) {
            return it->second;
        }
        return "";
    };
    
private:
    void ParseFieldTrials(const std::string& field_trials_string) {
        // Parse field trials in format: "Trial1/Value1/Trial2/Value2/"
        size_t pos = 0;
        while (pos < field_trials_string.length()) {
            size_t separator = field_trials_string.find('/', pos);
            if (separator == std::string::npos) {
                break;
            }
            std::string key = field_trials_string.substr(pos, separator - pos);
            pos = separator + 1;
            
            separator = field_trials_string.find('/', pos);
            if (separator == std::string::npos) {
                break;
            }
            std::string value = field_trials_string.substr(pos, separator - pos);
            pos = separator + 1;
            
            if (!key.empty()) {
                trials_[key] = value;
                std::cout << "Parsed field trial: " << key << " -> " << value << std::endl;
            }
        }
    }
    
    std::map<std::string, std::string> trials_;
};

#endif //WEBRTC_TEST_PEER_H
