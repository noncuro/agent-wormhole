"""Tests for transport abstraction."""
import asyncio
import pytest
from agent_wormhole.transport import DirectTransport, Transport


@pytest.mark.asyncio
async def test_direct_transport_host_peer_roundtrip():
    """DirectTransport host and peer can exchange frames."""
    host = DirectTransport.as_host(port=0)
    await host.connect()  # Starts listening, returns immediately

    actual_port = host.port
    assert actual_port > 0

    peer = DirectTransport.as_peer(hostname="127.0.0.1", port=actual_port)
    # Peer connects, then host accepts
    await peer.connect()
    await host.accept(timeout=5.0)

    # host -> peer
    await host.send_frame(b"hello from host")
    data = await peer.recv_frame()
    assert data == b"hello from host"

    # peer -> host
    await peer.send_frame(b"hello from peer")
    data = await host.recv_frame()
    assert data == b"hello from peer"

    await host.close()
    await peer.close()


@pytest.mark.asyncio
async def test_direct_transport_is_transport_subclass():
    assert issubclass(DirectTransport, Transport)


from agent_wormhole.transport import RelayTransport


@pytest.mark.asyncio
async def test_relay_transport_is_transport_subclass():
    assert issubclass(RelayTransport, Transport)
