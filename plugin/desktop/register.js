let transport = {
  rest: null,
  setInterval: null,
  onEvent: null,
};

function StudioPane() {
  const rootRef = useRef(null);
  const [model, setModel] = useState({ backend: "loading" });
  const [frame, setFrame] = useState(null);
  const selectedRun = useRef("");
  const selectedIteration = useRef(null);

  useEffect(() => {
    let stopped = false;

    function load(prefer) {
      if (prefer) selectedRun.current = prefer;
      const rest = transport.rest;
      if (typeof rest !== "function") {
        if (!stopped) {
          setModel({
            backend: "offline",
            message: "Part studio can't reach the plugin backend. Enable photo-to-part and rescan plugins. The six tools still run without this pane.",
          });
        }
        return Promise.resolve();
      }
      return Promise.resolve(rest("/runs"))
        .then((listed) => {
          const runs = listed && Array.isArray(listed.runs) ? listed.runs : [];
          if (!runs.length) {
            if (!stopped) setModel({ backend: "ready", runs: [], run: null });
            return null;
          }
          let id = selectedRun.current;
          if (!id || !runs.some((item) => item.id === id)) id = runs[0].id;
          selectedRun.current = id;
          return Promise.resolve(rest("/runs/" + encodeURIComponent(id))).then((body) => ({ runs, id, body }));
        })
        .then((packed) => {
          if (!packed || stopped) return;
          if (!packed.body || packed.body.ok === false) {
            throw new Error((packed.body && packed.body.error) || "Run unavailable");
          }
          setModel({
            backend: "ready",
            runs: packed.runs,
            selectedRun: packed.id,
            selectedIteration: selectedIteration.current,
            run: applyFrame(packed.body.run, frame),
          });
        })
        .catch((error) => {
          if (stopped) return;
          setModel({
            backend: "offline",
            message: (error && error.message) || "Part studio could not refresh.",
          });
        });
    }

    load();
    let timer = null;
    if (typeof transport.setInterval === "function") {
      timer = transport.setInterval(() => load(), 2000);
    }
    let off = null;
    if (typeof transport.onEvent === "function") {
      off = transport.onEvent("plugin.photo-to-part.run.updated", (event) => {
        const payload = event && event.payload ? event.payload : event;
        load(payload && payload.run_id ? payload.run_id : "");
      });
    }
    return () => {
      stopped = true;
      if (typeof timer === "function") timer();
      if (typeof off === "function") off();
    };
  }, [frame]);

  useEffect(() => {
    if (!rootRef.current) return;
    mountPane(
      rootRef.current,
      model,
      {
        onSelectRun(id) {
          selectedRun.current = id;
          selectedIteration.current = null;
          setFrame(null);
        },
        onSelectIteration(item) {
          selectedIteration.current = item && item.n;
          hydrateIteration(item);
        },
      },
      PANE_CSS
    );
  }, [model]);

  function hydrateIteration(item) {
    const rest = transport.rest;
    const id = selectedRun.current;
    if (typeof rest !== "function" || !id || !item) return;
    const pairs = [
      ["overlay", item.overlay_path],
      ["photo", item.photo_path],
      ["render", item.render_path],
      ["compare", item.compare_path],
    ];
    const images = {};
    let chain = Promise.resolve();
    pairs.forEach((pair) => {
      const key = pair[0];
      const rel = pair[1];
      if (!rel) return;
      chain = chain.then(() =>
        rest("/media?run=" + encodeURIComponent(id) + "&path=" + encodeURIComponent(rel))
      ).then((body) => {
        if (body && body.ok && typeof body.data_url === "string") images[key] = body.data_url;
      });
    });
    chain.then(() => setFrame({ n: item.n, images })).catch(() => setFrame({ n: item.n, images }));
  }

  return jsx("div", { ref: rootRef, className: "p2p-host" });
}

function applyFrame(run, frame) {
  if (!frame || !run) return run;
  const images = Object.assign({}, run.images || {}, frame.images || {});
  return Object.assign({}, run, { images, iteration: frame.n || run.iteration });
}

function registerPartStudio(ctx) {
  if (!ctx || typeof ctx.register !== "function") return false;
  transport = {
    rest: typeof ctx.rest === "function" ? (path, opts) => ctx.rest(path, opts) : null,
    setInterval: typeof ctx.setInterval === "function" ? (fn, ms) => ctx.setInterval(fn, ms) : null,
    onEvent: host && typeof host.onEvent === "function" ? (name, fn) => host.onEvent(name, fn) : null,
  };
  if (typeof ctx.onDispose === "function") {
    ctx.onDispose(() => {
      const style = document.getElementById("p2p-pane-style");
      if (style) style.remove();
    });
  }
  try {
    ctx.register({
      id: "studio",
      title: "Part studio",
      area: "panes",
      order: 42,
      data: { placement: "right", width: "640px" },
      render: () => jsx(StudioPane, {}),
    });
  } catch (err) {
    return false;
  }
  return true;
}

export default {
  id: "photo-to-part",
  name: "Part studio",
  defaultEnabled: true,
  register: registerPartStudio,
};
