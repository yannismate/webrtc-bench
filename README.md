# webrtc-bench

## Architecture
The testbed is split into 2 main components, the peer and the orchestrator, which are connected using a custom WebSocket protocol.
The peer is responsible for executing tests cases and collecting metrics during execution.
The orchestrator owns the test suite configuration and configures all connected peers according to the configured tests.
It also forwards signalling data between peers and collects all collected metrics and data after a test has completed.  

The bench supports multiple types of tests found in `internal/cases`, including the following:
- iperf3 (bandwidth test)
- Pion (WebRTC)
- libwebrtc (WebRTC, using custom C++ wrapper around Google's WebRTC)
- chromium (WebRTC, using headless chromium)
- Teams (WebRTC, using headless chromium, connecting to other peer through Microsoft Teams meeting)

The peer also supports parallel execution of shell commands, or UDP/ICMP pings, as well as the collection of Starlink obstruction map data through gRPC.

## Building
To build the testbed, you will need `Go 1.24+`.  
The codebase produces 2 binaries, the Orchestrator and the Peer. To build them execute the following commands:
- `go build -o orchestrator cmd/orchestrator/orchestrator.go`
- `go build -o peer cmd/peer/peer.go`

### Custom libwebtc
To make modifications to libwebrtc, clone [Google's WebRTC repository](https://webrtc.googlesource.com/src) on branch `branch_7401`.  
Apply the diff in `additional_code/libwebrtc_diffs` and use the following args.gn to build libwebrtc following Google's instructions:
```
is_debug = false
is_component_build = false
rtc_include_tests = false
treat_warnings_as_errors = false
use_ozone = true
rtc_use_x11 = false
use_rtti = true
rtc_build_examples = false
rtc_exclude_audio_processing_module = true
rtc_use_h264 = true
proprietary_codecs = true
ffmpeg_branding = "Chrome"
```
  
This custom libwebrtc can than be linked into gcc-tester, the custom wrapper around libwebrtc that is used in the test bed.
ARM builds require an additional `args.gn` flag.
All code and build scripts can be found in `additional_code/gcc-tester`.  
Replace the current binary in the `bin` folder with your newly built version.

### Chromium
Custom builds of chromium require a custom libwebrtc build for additional metrics and to differ from publicly available builds.
Clone the [Chromium Source](https://source.chromium.org/) on branch `branch_7401`.
Set up a repository with your customized version of libwebrtc and change the `.gclient` file in the Chromium repository to the following:
```
solutions = [
  {
    "name": "src",
    "url": "https://chromium.googlesource.com/chromium/src.git",
    "managed": False,
    "custom_deps": {
        "src/third_party/webrtc": "<custom libwebrtc git>@<commit hash>"
    },
    "custom_vars": {
        "checkout_pgo_profiles": True
    },
  },
]
```
Then build a headless version of chromium using the following `args.gn` with the instructions in the Chromium repository:
```
import("//build/args/headless.gn")
is_debug = false
is_official_build = true
symbol_level = 0
blink_symbol_level = 0
headless_use_prefs = true
chrome_pgo_phase = 0
treat_warnings_as_errors = false
proprietary_codecs=true
media_use_openh264=true
ffmpeg_branding="Chrome"
```
Replace the folders in `bin` with your modified version.
ARM builds require an additional `args.gn` flag.

### Docker Build
The testbed docker image can be built using Docker Buildx with the following command:
`docker buildx  build --platform linux/amd64,linux/arm64 . -t "IMAGE_NAME:IMAGE_TAG"`  
This is a shared image that contains both the peer and orchestrator.  
If you do not require ARM support or did not build Chromium or gcc-tester for ARM, remove the second build platform.

## Licensing

This repository is licensed under the MIT License, except for the contents
of the `bin/headless_shell_amd64` and `bin/headless_shell_arm64` directories, which are derived from Chromium and
are licensed under the Chromium (BSD-style) license.
