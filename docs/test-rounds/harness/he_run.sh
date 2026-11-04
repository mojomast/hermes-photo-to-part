: "${HERMES_HOME:?set HERMES_HOME}"; export PHOTOPART_BUILD_APPROVAL=allow
id=$1; D=${ROUND_DIR:?set ROUND_DIR}/he/$id; cd $D
s=$(date +%s); timeout 1500 hermes chat --query-file prompt.txt --oneshot --yolo --max-turns 40 > hermes.log 2>&1
echo "exit=$? secs=$(( $(date +%s)-s ))" > time.txt
