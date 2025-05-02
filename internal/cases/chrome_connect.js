const iceServers = ICE_SERVERS.map((iceUrl) => ({urls: iceUrl}));
const doOffer = DO_OFFER;

function log(msg) {
    if (msg instanceof String) {
        sendManagementMessage(JSON.stringify({type: "log", value: msg}))
    } else {
        sendManagementMessage(JSON.stringify({type: "log", value: JSON.stringify(msg)}))
    }
}

window.onerror = function(msg, url, line, col, error) {
    log(`Error: ${error}`);
};

const peerConnection = new RTCPeerConnection({
    iceServers: iceServers
});

let dataChannel;
if (doOffer) {
    dataChannel = peerConnection.createDataChannel("test");
    dataChannel.onopen = () => {
        log("Data channel connected");
    };
}

peerConnection.onconnectionstatechange = e => {
    log("Connection state changed: " + peerConnection.connectionState);
};

peerConnection.onicecandidate = ({candidate}) => {
    if (!candidate) return;

    sendManagementMessage(JSON.stringify({type: "candidates", value: JSON.stringify(candidate)}))
};


async function start() {
    if (doOffer) {
        log("Sending offer...");
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);

        sendManagementMessage(JSON.stringify({type: "sdp", value: JSON.stringify(offer)}))
    }
}

async function stop() {
    peerConnection.close();
}

async function receiveManagementMessage(type, msgString) {
    if (type === "sdp") {
        await peerConnection.setRemoteDescription(new RTCSessionDescription(JSON.parse(msgString)));

        if (!doOffer) {
            log("Sending answer");
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);

            sendManagementMessage(JSON.stringify({type: "sdp", value: JSON.stringify(answer)}));
        } else {
            log("Set remote description, RTC should be ready.");
        }
    } else if (type === "candidates") {
        await peerConnection.addIceCandidate(new RTCIceCandidate(JSON.parse(msgString)));
    }
}

// Required to return for chromedp evaluation
[""]