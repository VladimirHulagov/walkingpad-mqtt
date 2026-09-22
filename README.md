# walkingpad-mqtt

WalkingPad A1 Pro (WPA1F-Pro) → MQTT мост для Home Assistant. Держит постоянное
BLE-подключение к дорожке (проприетарный WiLink-протокол KingSmith, сервис
0xFE00), публикует телеметрию и discovery-энтити, принимает команды.

Важно: дорожка допускает одно BLE-подключение — пока работает сервис,
приложение WalkingPad на телефоне не подключится.

## Установка

    python3 -m venv .venv
    .venv/bin/pip install -e '.[dev]'

(pypi.org на этом хосте закрыт DNS-фильтром; ~/.config/pip/pip.conf указывает
на зеркало Tsinghua.)

## Настройка

1. Включите дорожку (кнопка на корпусе / удержание MODE).
2. `.venv/bin/walkingpad-mqtt --discover` — покажет MAC.
3. `mkdir -p ~/.config/walkingpad && cp config/config.example.toml ~/.config/walkingpad/config.toml`
4. Впишите MAC и адрес MQTT-брокера. Для TLS-брокера: port = 8883 и tls = true

## Запуск вручную

    .venv/bin/walkingpad-mqtt          # foreground
    .venv/bin/walkingpad-mqtt -v       # debug-логи

## Автозапуск (systemd user)

    mkdir -p ~/.config/systemd/user
    cp systemd/walkingpad-mqtt.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now walkingpad-mqtt
    loginctl enable-linger $USER   # работа без логина

Логи: `journalctl --user -u walkingpad-mqtt -f`

## Home Assistant

Энтити (MQTT discovery, устройство "WalkingPad A1 Pro"):

- sensor: скорость, дистанция, шаги, время сессии, калории (расчётные), состояние
- binary_sensor: BLE связь
- button: старт, стоп
- number: целевая скорость (0.5–6 км/ч)

Сервис сам активирует ручной режим дорожки при подключении (как приложение
KingSmith); без этого дорожка отвечает на команды только писком.

## Тесты

    .venv/bin/pytest

## Если дорожка не подключается

После аварийного завершения (SIGKILL, зависание) BlueZ может держать висячее
BLE-соединение — дорожка перестаёт рекламироваться. Сервис сам лечит это
(каждая 3-я неудачная попытка). Вручную: `bluetoothctl disconnect <MAC>`.

## Ограничения

- Хост BLE — машина, где работает сервис: во время её сна/выключения
  управление дорожкой невозможно. Команды на это время НЕ накапливаются
  (намеренно: ремень не должен стартовать без ведома спустя минуты).
  Признак живого моста — `binary_sensor.walkingpad_connected` = on и
  обновляющийся `sensor.walkingpad_belt_state`.
- Сама дорожка периодически засыпает и перестаёт рекламироваться; сервис
  переподключится, когда её разбудят (кнопкой или наступанием в auto-режиме).
- Дорожка допускает одно BLE-подключение: пока работает сервис, приложение
  WalkingPad не подключится (и наоборот).
