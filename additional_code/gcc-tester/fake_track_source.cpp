#include "fake_track_source.h"

#include <api/video/i420_buffer.h>
#include <chrono>
#include <iostream>
#include <rtc_base/thread.h>
#include <thread>

static auto g_frame_worker_thread = webrtc::Thread::Create();

void FakeVideoSource::StartSource(int output_fps) {
    std::cout << "[fake-source] Starting fake frame source now" << std::endl;
    g_frame_worker_thread->Start();
    g_frame_worker_thread->PostTask([this, output_fps]() {
        std::cout << "[fake-source] Frame worker thread started." << std::endl;
        constexpr int width = 1280;
        constexpr int height = 720;
        constexpr int input_fps = 60;
        auto frame_interval_ns = std::chrono::nanoseconds(1'000'000'000 / output_fps);

        std::cout << "[fake-source] Fake source configured as " << width << "x" << height << "@" << input_fps << std::endl;

        webrtc::scoped_refptr<webrtc::I420Buffer> buffer = webrtc::I420Buffer::Create(width, height);
        webrtc::I420Buffer::SetBlack(buffer.get());

        auto next_frame_time = std::chrono::system_clock::now();

        if (source_type_ == FFMPEG) {
            std::string source = "-f lavfi -i testsrc=size=" + std::to_string(width) + "x" + std::to_string(height) + ":rate=" + std::to_string(input_fps);
            if (!ffmpeg_source_file_.empty() && ffmpeg_source_file_ != "testsrc") {
                source = "-i " + ffmpeg_source_file_;
            }

            std::string ffmpeg_command = "ffmpeg -hide_banner -loglevel error"
                                         " -re ";
            ffmpeg_command += source;
            ffmpeg_command += " -vf drawtext=\"fontsize=30:text='%{gmtime\\:%T.%N} - "
                              "%{frame_num}':fontcolor=white:x=4:y=4:box=1:boxcolor=black@0.8\""
                              " -s " + std::to_string(width) + "x" + std::to_string(height) +
                              " -r " + std::to_string(output_fps) + " -f rawvideo"
                              " -pix_fmt yuv420p"
                              " -";

            std::cout << "[fake-source] Starting ffmpeg source: " << ffmpeg_command << std::endl;

            constexpr int frame_size = width * height * 3 / 2;
            FILE *pipe = popen(ffmpeg_command.c_str(), "r");
            std::vector<uint8_t> ffmpeg_buffer(frame_size);

            while (fread(ffmpeg_buffer.data(), 1, frame_size, pipe) == frame_size && !is_stopping_) {
                memcpy(buffer->MutableDataY(), ffmpeg_buffer.data(), width * height);
                memcpy(buffer->MutableDataU(), ffmpeg_buffer.data() + width * height, (width / 2) * (height / 2));
                memcpy(buffer->MutableDataV(), ffmpeg_buffer.data() + width * height + (width / 2) * (height / 2),
                       (width / 2) * (height / 2));

                auto us_timestamp = std::chrono::duration_cast<std::chrono::microseconds>(
                                            std::chrono::system_clock::now().time_since_epoch())
                                            .count();

                webrtc::VideoFrame frame = webrtc::VideoFrame::Builder()
                                                   .set_video_frame_buffer(buffer)
                                                   .set_timestamp_us(us_timestamp)
                                                   .build();

                this->OnFrameCaptured(frame);
            }
            pclose(pipe);
            std::cout << "[fake-source] ffmpeg source stopped" << std::endl;
        }

        if (source_type_ != FFMPEG) {
            std::cout << "[fake-source] Starting input source" << std::endl;
            while (!is_stopping_) {
                if (source_type_ == RANDOM_NOISE) {
                    // Fill the buffer with random data
                    for (int i = 0; i < width * height; ++i) {
                        buffer->MutableDataY()[i] = static_cast<uint8_t>(rand() % 256);
                    }
                    for (int i = 0; i < (width / 2) * (height / 2); ++i) {
                        buffer->MutableDataU()[i] = static_cast<uint8_t>(rand() % 256);
                        buffer->MutableDataV()[i] = static_cast<uint8_t>(rand() % 256);
                    }
                }

                auto us_timestamp =
                        std::chrono::duration_cast<std::chrono::microseconds>(next_frame_time.time_since_epoch())
                                .count();
                webrtc::VideoFrame frame = webrtc::VideoFrame::Builder()
                                                   .set_video_frame_buffer(buffer)
                                                   .set_timestamp_us(us_timestamp)
                                                   .build();

                this->OnFrameCaptured(frame);

                next_frame_time += std::chrono::duration_cast<std::chrono::system_clock::duration>(frame_interval_ns);
                std::this_thread::sleep_until(next_frame_time);
            }
        }
    });
}

void FakeVideoSource::StopSource() {
    is_stopping_ = true;
    g_frame_worker_thread->Stop();
}
