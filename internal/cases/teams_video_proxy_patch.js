console.log("Applying RTCPeerConnection proxy patch")

const OriginalRTCPeerConnection = window.RTCPeerConnection;

// track RTCPeerConnection instances in global array
window.peerConnections = [];

window.RTCPeerConnection = function(...args) {
    console.log("New RTCPeerConnection is constructed with patched constructor!");
    const pc = new OriginalRTCPeerConnection(...args);
    window.peerConnections.push(pc);
    console.log('New RTCPeerConnection created:', pc);
    return pc;
};

window.RTCPeerConnection.prototype = OriginalRTCPeerConnection.prototype;
Object.setPrototypeOf(window.RTCPeerConnection, OriginalRTCPeerConnection);

// Remove from list when closed
const originalClose = OriginalRTCPeerConnection.prototype.close;
OriginalRTCPeerConnection.prototype.close = function(...args) {
    const idx = window.peerConnections.indexOf(this);
    if (idx !== -1) window.peerConnections.splice(idx, 1);
    return originalClose.apply(this, args);
};
