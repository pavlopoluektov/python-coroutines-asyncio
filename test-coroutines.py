"""
Minimal async implementation - just deque, generators, and select
"""

from collections import deque
import socket
import select
import time


def run(*coroutines):
    """Run multiple coroutines concurrently until all done"""
    tasks = deque(coroutines)
    waiting = {}  # sock -> (coro, 'r'/'w')
    results = {}  # coro -> result
    
    while tasks or waiting:
        # Run ready tasks
        while tasks:
            coro = tasks.popleft()
            try:
                sock, mode = next(coro)
                waiting[sock] = (coro, mode)
            except StopIteration as e:
                results[coro] = e.value
        
        # Wait for I/O
        if waiting:
            readers = [s for s, (c, m) in waiting.items() if m == 'r']
            writers = [s for s, (c, m) in waiting.items() if m == 'w']
            
            readable, writable, _ = select.select(readers, writers, [])
            
            for sock in readable + writable:
                coro, _ = waiting.pop(sock)
                tasks.append(coro)
    
    return list(results.values())


def async_socket(host, port, retries=3):
    """Async context manager - yields I/O ops, then socket, with cleanup"""
    sock = None
    last_error = None
    
    # Connect with retries
    for attempt in range(retries):
        try:
            sock = socket.socket()
            sock.setblocking(False)
            try:
                sock.connect((host, port))
            except BlockingIOError:
                pass
            
            yield (sock, 'w')  # wait for writable
            
            err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if err != 0:
                raise Exception(f"Connection error: {err}")
            
            break  # Success!
            
        except Exception as e:
            if sock:
                sock.close()
                sock = None
            last_error = e
            if attempt < retries - 1:
                time.sleep(0.1 * (2 ** attempt))
    
    if not sock:
        raise Exception(f"Failed after {retries} attempts: {last_error}")
    
    try:
        yield sock  # Provide resource
    finally:
        sock.close()


def async_enter(context_gen):
    """Enter async context - forward I/O ops, return socket"""
    for value in context_gen:
        if isinstance(value, socket.socket):
            return value
        yield value


def async_exit(context_gen):
    """Exit async context - trigger cleanup"""
    try:
        context_gen.close()
    except StopIteration:
        pass


def http_request(url, method='GET', data=None):
    """HTTP request using async context manager"""
    url = url.replace('http://', '')
    host, _, path = url.partition('/')
    path = '/' + path if path else '/'
    
    # Create context manager
    ctx = async_socket(host, 80)
    
    # Enter context (get socket)
    sock = yield from async_enter(ctx)
    
    try:
        # Build request
        headers = f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n"
        
        if data:
            body = data.encode() if isinstance(data, str) else data
            headers += f"Content-Length: {len(body)}\r\n"
            headers += "Content-Type: application/json\r\n"
            headers += "\r\n"
            request = headers.encode() + body
        else:
            headers += "\r\n"
            request = headers.encode()
        
        # Send (non-blocking)
        sent = 0
        while sent < len(request):
            try:
                n = sock.send(request[sent:])
                sent += n
            except BlockingIOError:
                yield (sock, 'w')
        
        # Receive
        response = b""
        while True:
            yield (sock, 'r')
            
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        # Socket closed, parse response                      
                        body = response.decode('utf-8', errors='ignore').split('\r\n\r\n', 1)[1]
                        return body
                    response += chunk
                except BlockingIOError:
                    break  # No more data available right now, wait for next select
    finally:
        async_exit(ctx)  # Exit context (cleanup)


def task1():
    """First concurrent task - GET request"""
    print("[Task 1] Starting GET request...")
    
    try:
        result = yield from http_request("http://httpbin.org/get")
        print(f"[Task 1] Got {len(result)} bytes")
        print(f"[Task 1] Response: {result}...")
    except Exception as e:
        print(f"[Task 1] Error: {e}")
    
    return "Task 1 done"


def task2():
    """Second concurrent task - POST request"""
    print("[Task 2] Starting POST request...")
    
    try:
        result = yield from http_request(
            "http://httpbin.org/post",
            method='POST',
            data='{"task": 2, "concurrent": true}'
        )
        print(f"[Task 2] Got {len(result)} bytes")
        print(f"[Task 2] Response: {result}...")
    except Exception as e:
        print(f"[Task 2] Error: {e}")
    
    return "Task 2 done"


if __name__ == "__main__":
    print("=" * 60)
    print("Running 2 concurrent HTTP requests")
    print("=" * 60)
    
    results = run(task1(), task2())
    
    print("\n" + "=" * 60)
    for i, result in enumerate(results, 1):
        print(f"✓ Task {i}: {result}")
    print("=" * 60)
