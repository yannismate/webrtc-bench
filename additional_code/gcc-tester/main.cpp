#include <iostream>
#include <modules/video_coding/codecs/h264/include/h264.h>
#include "webrtc_test_peer.h"

std::string UnescapeSDP(const std::string& s);

int main(int argc, char* argv[]) {
    bool is_sender = true;
    bool auto_start = false;
    int target_bitrate = 10000000; // 10 Mbps
    int target_fps = 60;
    std::vector<std::string> ice_servers = {"stun:stun.l.google.com:19302"};
    int stat_interval_ms = 100; // 100 ms
    std::string use_real_codec;
    bool use_ffmpeg_source = false;
    std::string ffmpeg_source_file;
    bool use_ffmpeg_output = false;
    std::optional<int> min_jitter_buffer_ms = std::nullopt;
    std::string field_trials;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--sender" && i + 1 < argc) {
            std::string val = argv[++i];
            is_sender = (val == "true" || val == "1");
        } else if (arg == "--autostart" && i + 1 < argc) {
            std::string val = argv[++i];
            auto_start = (val == "true" || val == "1");
        } else if (arg == "--bitrate" && i + 1 < argc) {
            target_bitrate = std::stoi(argv[++i]);
        } else if (arg == "--target-fps" && i + 1 < argc) {
            target_fps = std::stoi(argv[++i]);
            if (target_fps <= 0) {
                target_fps = 60;
            }
        } else if (arg == "--ice" && i + 1 < argc) {
            ice_servers.clear();
            ice_servers.emplace_back(argv[++i]);
        } else if (arg == "--stat-interval" && i + 1 < argc) {
            stat_interval_ms = std::stoi(argv[++i]);
        } else if (arg == "--use-real-codec" && i + 1 < argc) {
            std::string val = argv[++i];
            use_real_codec = val;
        } else if (arg == "--use-ffmpeg-source" && i + 1 < argc) {
            std::string val = argv[++i];
            use_ffmpeg_source = (val == "true" || val == "1");
        } else if (arg == "--ffmpeg-source-file"  && i + 1 < argc) {
            ffmpeg_source_file = argv[++i];
        } else if (arg == "--use-ffmpeg-output" && i + 1 < argc) {
            std::string val = argv[++i];
            use_ffmpeg_output = (val == "true" || val == "1");
        } else if (arg == "--min-jitter-buffer-ms" && i + 1 < argc) {
            min_jitter_buffer_ms = std::stoi(argv[++i]);
        } else if (arg == "--field-trials" && i + 1 < argc) {
            field_trials = argv[++i];
        }
    }

    if (use_real_codec == "h264") {
        auto codecs = webrtc::SupportedH264Codecs(true);
        if (codecs.empty()) {
            std::cout << "H264 missing (likely can't load libopenh264.so)" << std::endl;
        } else {
            std::cout << "H264 available!" << std::endl;
        }
    }

    std::cout << "Configured: is_sender: " << (is_sender ? "true" : "false")
        << ", target_bitrate: " << target_bitrate  << ", target_fps: " << target_fps
        << ", stat_interval: " << stat_interval_ms << std::endl;

    std::cout << "Configured FieldTrials: " << field_trials << std::endl;

    auto test_peer = std::make_shared<WebRTCTestPeer>(is_sender, target_bitrate, target_fps, ice_servers,
        stat_interval_ms, use_real_codec, use_ffmpeg_source, ffmpeg_source_file, use_ffmpeg_output,
        min_jitter_buffer_ms, field_trials);

    if (auto_start) {
        test_peer->Start();
    }

    std::string command;
    while (std::getline(std::cin, command)) {
        if (command.rfind("START", 0) == 0) {
            test_peer->Start();
        } else if (command.rfind("STOP", 0) == 0) {
            std::cout << "Received STOP command..." << std::endl;
            test_peer->Stop();
            std::exit(0);
        } else if (command.rfind("SDP/", 0) == 0) {
            size_t second_slash = command.find('/', 4);
            if (second_slash == std::string::npos) {
                std::cerr << "Invalid command!" << std::endl;
                test_peer->Stop();
                return -1;
            }
            auto type = command.substr(4, second_slash - 4);
            auto sdp_str = UnescapeSDP(command.substr(second_slash + 1));

            webrtc::SdpParseError parse_error;
            if (type == "offer") {
                auto recv_sdp = webrtc::CreateSessionDescription(webrtc::SdpType::kOffer, sdp_str, &parse_error);
                if (!parse_error.description.empty()) {
                    std::cerr << "SDP parse error: " << parse_error.description << std::endl;
                    test_peer->Stop();
                    return -1;
                }
                test_peer->ReceiveSDP(recv_sdp.release());
            } else if (type == "answer") {
                auto recv_sdp = webrtc::CreateSessionDescription(webrtc::SdpType::kAnswer, sdp_str, &parse_error);
                if (!parse_error.description.empty()) {
                    std::cerr << "SDP parse error: " << parse_error.description << std::endl;
                    test_peer->Stop();
                    return -1;
                }
                test_peer->ReceiveSDP(recv_sdp.release());
            } else if (type == "candidate") {
                auto candidate = webrtc::CreateIceCandidate("0", 0, sdp_str, &parse_error);
                if (!parse_error.description.empty()) {
                    std::cerr << "ICE Candidate parse error: " << parse_error.description << std::endl;
                    test_peer->Stop();
                    return -1;
                }
                test_peer->ReceiveICECandidate(candidate);
            } else {
                test_peer->Stop();
                std::cerr << "Unknown SDP type!" << std::endl;
                return -1;
            }
        } else {
            test_peer->Stop();
            std::cerr << "Unknown command: " << command << std::endl;
            return -1;
        }
    }
}

std::string UnescapeSDP(const std::string& s) {
    std::string result;
    result.reserve(s.size());
    for (size_t i = 0; i < s.size(); ++i) {
        if (s[i] == '\\' && i + 1 < s.size()) {
            if (s[i + 1] == 'r') {
                result += '\r';
                ++i;
            } else if (s[i + 1] == 'n') {
                result += '\n';
                ++i;
            } else {
                result += s[i];
            }
        } else {
            result += s[i];
        }
    }
    return result;
}
