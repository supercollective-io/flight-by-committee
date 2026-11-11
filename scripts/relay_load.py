"""Synthetic localhost capacity/recovery trial; never starts or claims FlightGear."""
import argparse
import asyncio
import json
import random
import statistics
import threading
import time

import aiohttp
from aiohttp.test_utils import TestServer
from scripts.relay import Relay
from scripts.relay_bridge import RemoteState, connection_loop


def distribution(values):
    ordered = sorted(values)
    return dict(samples=len(values), p50_ms=round(statistics.median(values), 2),
                p95_ms=round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 2),
                max_ms=round(max(values), 2))


async def trial(clients=140, rounds=40, jitter_ms=30):
    randomiser = random.Random(10)
    relay = Relay('p'*32, 'b'*32, 'https://flight.supercollective.io')
    server = TestServer(relay.app())
    await server.start_server()
    state = RemoteState({'expiry_s': 1.})
    state.ready = state.connected = True
    state.generation = 1.
    state.throttle = .45
    poll_rtt, intervals, last_frame = [], [], None
    original_accept = state.accept
    def measured_accept(frame, nonce, sent):
        nonlocal last_frame
        original_accept(frame, nonce, sent)
        now = time.monotonic()
        poll_rtt.append((now-sent)*1000)
        if last_frame is not None:
            intervals.append((now-last_frame)*1000)
        last_frame = now
    state.accept = measured_accept
    stop = threading.Event()
    bridge = asyncio.create_task(connection_loop(state, str(server.make_url('/ws/bridge')), 'b'*32, stop))
    phones, replies, rtt, propagation = [], [], [], []
    started = time.monotonic()
    connector = aiohttp.TCPConnector(limit=clients+10)
    async with aiohttp.ClientSession(connector=connector) as session:
        joins = asyncio.Semaphore(24)
        async def join():
            async with joins:
                return await open_phone()
        async def open_phone():
            ws = await session.ws_connect(server.make_url('/ws/participant?key='+'p'*32), headers={'Origin': relay.origin})
            await ws.send_json(dict(kind='input', epoch=None, challenge=None, controls=None, release_brakes=False))
            return ws, await ws.receive_json()
        async def wait_for(predicate, timeout=2):
            deadline = time.monotonic()+timeout
            while not predicate():
                if time.monotonic() >= deadline:
                    raise AssertionError('Recovery/propagation deadline missed')
                await asyncio.sleep(.002)
        async def send(index, roll):
            await asyncio.sleep(randomiser.uniform(0, jitter_ms/1000))
            ws, previous = phones[index], replies[index]
            sent = time.monotonic()
            await ws.send_json(dict(kind='input', epoch=previous['epoch'], challenge=previous['challenge'], controls=dict(roll=roll, pitch=0, rudder=0, brake=0, throttle=None), release_brakes=False))
            replies[index] = await ws.receive_json()
            rtt.append((time.monotonic()-sent)*1000)
        try:
            await wait_for(lambda: relay.state.ready)
            joined = await asyncio.gather(*(join() for _ in range(clients)))
            phones, replies = map(list, zip(*joined))
            for iteration in range(rounds):
                tick = time.monotonic()
                if iteration == rounds//2:
                    # Induce 20% participant loss; returning connections must handshake.
                    returning = max(1, clients//5)
                    await asyncio.gather(*(ws.close() for ws in phones[:returning]))
                    await wait_for(lambda: len(relay.sockets) <= clients-returning+1)
                    replacement = await asyncio.gather(*(join() for _ in range(returning)))
                    for index, (ws, reply) in enumerate(replacement):
                        phones[index], replies[index] = ws, reply
                roll = .5 if iteration % 2 else -.5
                await asyncio.gather(*(send(index, roll) for index in range(clients)))
                await wait_for(lambda: state.fresh() and abs(state.values['roll']-roll) < 1e-6)
                propagation.append((time.monotonic()-tick)*1000)
                if relay.state.status()['count'] != clients:
                    raise AssertionError('Participant count changed under load')
                await asyncio.sleep(max(0, .1-(time.monotonic()-tick)))
            old_epoch = relay.epoch
            await relay.bridge.close()
            await wait_for(lambda: relay.epoch != old_epoch)
            await asyncio.sleep(.55)
            if state.fresh() or state.values['roll'] != 0 or state.values['throttle'] is not None:
                raise AssertionError('Bridge disconnect retained momentary commands')
            await wait_for(lambda: relay.state.ready)
            if relay.state.status()['count']:
                raise AssertionError('Reconnect replayed old participants')
            # Recover one phone, then reset the local simulator generation.
            replies[0] = await send_and_reply(phones[0], None, None)
            await send(0, .5)
            await wait_for(state.fresh)
            with state.lock:
                state.generation = 2.
                state.invalidate()
            await wait_for(lambda: relay.generation == 2.)
            if state.fresh() or relay.state.status()['count']:
                raise AssertionError('Generation reset replayed controls')
            result = dict(kind='synthetic localhost, no simulator', clients=clients, rounds=rounds,
                          injected_jitter_ms=[0,jitter_ms], elapsed_s=round(time.monotonic()-started, 2),
                          input_round_trip=distribution(rtt), aggregate_round_trip=distribution(poll_rtt),
                          bridge_frame_interval=distribution(intervals), batch_input_to_bridge=distribution(propagation),
                          participant_disconnect_rejoin='passed (20%)', bridge_disconnect_recovery='passed',
                          simulator_generation_reset='passed')
            return result
        finally:
            stop.set()
            await asyncio.gather(*(ws.close() for ws in phones), return_exceptions=True)
            await asyncio.wait_for(bridge, 3)
            await server.close()


async def send_and_reply(ws, epoch, challenge):
    await ws.send_json(dict(kind='input', epoch=epoch, challenge=challenge, controls=None, release_brakes=False))
    return await ws.receive_json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clients', type=int, default=140)
    parser.add_argument('--rounds', type=int, default=40)
    parser.add_argument('--jitter-ms', type=float, default=30)
    args = parser.parse_args()
    if not 2 <= args.clients <= 300 or args.rounds < 4 or not 0 <= args.jitter_ms <= 100:
        parser.error('Use 2–300 clients, at least 4 rounds and 0–100 ms jitter')
    print(json.dumps(asyncio.run(trial(args.clients, args.rounds, args.jitter_ms)), indent=2))


if __name__ == '__main__':
    main()
