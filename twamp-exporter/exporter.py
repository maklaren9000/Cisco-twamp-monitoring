import socket
import struct
import time
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

class PrometheusExporter(BaseHTTPRequestHandler):
    """
    HTTP-сервер, который обрабатывает запросы от Prometheus,
    опрашивает сетевое оборудование по протоколу TWAMP Light и возвращает метрики.
    """
    
    
    def do_GET(self):
        # Парсим входящий URL запроса от Prometheus
        # Parse the incoming request URL from Prometheus
        parsed_url = urlparse(self.path)
        
        # Обрабатываем запросы только на эндпоинт /probe
        # Process requests only to the /probe endpoint
        if parsed_url.path == '/probe':
            query_components = parse_qs(parsed_url.query)
            # Извлекаем IP-адрес целевого роутера из параметров (?target=X.X.X.X)
            target = query_components.get("target", [None])
            
            if not target or not target[0]:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing target parameter")
                return

            # Запускаем сетевой опрос роутера по TWAMP Light
            # Launch a network poll of the router using TWAMP Light
            rtt, success = self.get_twamp_rtt(target[0])
            
            # Формируем успешный HTTP-ответ в формате Prometheus (текст версии 0.0.4)
            # Generate a successful HTTP response in Prometheus format (text version 0.0.4)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            
            # Записываем метрики в выходной поток HTTP-ответа
            # Write metrics to the HTTP response output stream
            metrics_output = (
                f"# HELP cisco_twamp_rtt_ms TWAMP Light Round Trip Time in milliseconds\n"
                f"# TYPE cisco_twamp_rtt_ms gauge\n"
                f"cisco_twamp_rtt_ms {rtt}\n"
            )
            self.wfile.write(metrics_output.encode())
        else:
            # На любые другие запросы отдаем 404 Not Found
            # For any other requests, we return 404 Not Found
            self.send_response(404)
            self.end_headers()

    def get_twamp_rtt(self, target_ip):
        """
        Отправляет тестовый UDP-пакет TWAMP Light на роутер и замеряет время ответа (RTT).
        """
        try:
            # Создаем стандартный UDP сокет
            # Create a standard UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Устанавливаем жесткий таймаут 0.8 сек, чтобы долгие задержки не вешали скрипт
            # Set a hard timeout of 0.8 seconds so that long delays don't hang the script
            sock.settimeout(0.8)
            
            # Привязываем сокет к локальному порту (контрольный порт TWAMP Sender)
            # Bind the socket to a local port (TWAMP Sender control port)
            sock.bind(("0.0.0.0", 20001)) 
            
            # Формируем бинарный пакет TWAMP Light (RFC 5357)
            # Структура заголовка: Sequence Number (4 байта), Timestamp (8 байт), Error Estimate (2 байта), TTL (1 байт)
            # 2208988800 — разница в секундах между эпохой NTP (1900) и эпохой Unix (1970)
            # Generate a TWAMP Light binary packet (RFC 5357)
            # Header structure: Sequence Number (4 bytes), Timestamp (8 bytes), Error Estimate (2 bytes), TTL (1 byte)
            # 2208988800 — the difference in seconds between the NTP epoch (1900) and the Unix epoch (1970)
            ntp_timestamp = (int(time.time()) + 2208988800) << 32
            packet_header = struct.pack(">I Q H B", 1, ntp_timestamp, 0, 255)
            
            # Добиваем пакет нулями до стандартного размера TWAMP-пакета (64 байта)
            # We pad the packet with zeros to the standard TWAMP packet size (64 bytes)
            packet = packet_header + b"\x00" * 49
            
            # Фиксируем точное время отправки пакета
            # We record the exact time of sending the packet
            t_start = time.time()
            
            # Отправляем UDP-пакет на стандартный порт TWAMP Light responder (862)
            # Send a UDP packet to the standard TWAMP Light responder port (862)
            sock.sendto(packet, (target_ip, 862))
            
            # Ждем ответный пакет от роутера Cisco
            # We are waiting for a response packet from the Cisco router
            data, addr = sock.recvfrom(1024)
            
            # Фиксируем время получения ответа
            # We record the time of receiving the response
            t_end = time.time()
            sock.close()
            
            # Рассчитываем итоговую задержку RTT в миллисекундах с округлением до 2 знаков
            # Calculate the final RTT delay in milliseconds, rounded to 2 digits
            rtt = round((t_end - t_start) * 1000, 2)
            return rtt, 1
            
        except Exception:
            # Если роутер недоступен, произошел таймаут или потеря пакета — возвращаем 0
            # If the router is unavailable, a timeout occurred, or a packet was lost, return 0
            if 'sock' in locals():
                sock.close()
            return 0.0, 0

if __name__ == '__main__':
    # Запуск HTTP-сервера экспортера на порту 9853
    # Start the exporter HTTP server on port 9853
    server = HTTPServer(('0.0.0.0', 9853), PrometheusExporter)
    print("Универсальный TWAMP-скрипт успешно запущен на порту 9853...") #replac if needed
    server.serve_forever()
