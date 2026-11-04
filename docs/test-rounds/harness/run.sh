export HERMES_HOME=${HERMES_HOME:?set HERMES_HOME} PHOTOPART_BUILD_APPROVAL=allow
cd ${ROUND_DIR:?set ROUND_DIR}/$1
img=$(ls *.jpg *.JPG *.png 2>/dev/null|head -1)
s=$(date +%s); timeout 2400 hermes chat --query-file prompt.txt --image "$img" --oneshot --yolo --max-turns 40 > hermes.log 2>&1; e=$?
echo "exit=$e secs=$(( $(date +%s)-s ))" > time.txt
