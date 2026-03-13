#!/bin/bash
# Скрипт для генерации речи через отдельный RHVoice-аддон (ha-rhvoice-addon)

MESSAGE="$1"
LANG="${2:-ru}"
FILENAME="$3"

if [ -z "$MESSAGE" ] || [ -z "$FILENAME" ]; then
    echo "Usage: $0 <text> <language> <output_file.pcm>"
    exit 1
fi

TIMESTAMP=$(date +%s)
TEMP_WAV="/tmp/tts_${TIMESTAMP}.wav"

# Определяем голос в зависимости от языка
if [ "$LANG" = "ru" ]; then
    VOICE="anna"
elif [ "$LANG" = "en" ]; then
    VOICE="slt"
else
    VOICE="anna"
fi

echo "🔊 Requesting RHVoice from separate addon: voice=$VOICE"

# Пробуем разные адреса для доступа к RHVoice-аддону
# Аддон definitio/ha-rhvoice-addon обычно доступен на порту 8080
RHVOICE_URLS=(
    "http://localhost:8080/say"
    "http://172.30.32.1:8080/say"
    "http://supervisor:8080/say"
    "http://rhvoice:8080/say"
)

SUCCESS=false
RESPONSE_MSG=""

for URL in "${RHVOICE_URLS[@]}"; do
    echo "Trying RHVoice at $URL"
    
    # Отправляем POST запрос с текстом (формат зависит от аддона)
    # Для definitio/ha-rhvoice-addon используем JSON
    RESPONSE_MSG=$(curl -X POST "$URL" \
        -H "Content-Type: application/json" \
        -d "{\"text\":\"$MESSAGE\",\"voice\":\"$VOICE\"}" \
        --output "$TEMP_WAV" \
        --write-out "%{http_code}" \
        --silent)
        
    if [ "$RESPONSE_MSG" = "200" ] && [ -f "$TEMP_WAV" ] && [ -s "$TEMP_WAV" ]; then
        echo "✅ RHVoice response received from $URL (HTTP 200)"
        SUCCESS=true
        break
    else
        echo "❌ Failed with HTTP $RESPONSE_MSG"
    fi
done

if [ "$SUCCESS" = false ]; then
    echo "❌ All RHVoice endpoints failed, falling back to Google TTS"
    /app/tts_generate_openipc.sh "$MESSAGE" "$LANG" "$FILENAME"
    exit $?
fi

echo "✅ RHVoice WAV created: $TEMP_WAV"

# Конвертируем в PCM 8000Hz, 16bit, mono для OpenIPC
ffmpeg -y -i "$TEMP_WAV" -ar 8000 -ac 1 -f s16le "$FILENAME" 2>/dev/null

if [ ! -f "$FILENAME" ]; then
    echo "❌ PCM conversion failed, falling back to Google TTS"
    /app/tts_generate_openipc.sh "$MESSAGE" "$LANG" "$FILENAME"
    exit $?
fi

# Удаляем временный файл
rm -f "$TEMP_WAV"

SIZE=$(wc -c < "$FILENAME")
echo "✅ RHVoice PCM file created: $FILENAME ($SIZE bytes)"
exit 0