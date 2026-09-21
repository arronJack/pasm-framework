// pasm-framework Java 客户端（零第三方依赖，用 JDK 11+ 的 java.net.http）
//
// 用法：
//   import pasm.PasmClient;
//
//   try (var c = new PasmClient("http://127.0.0.1:8080", "your-secret")) {
//       System.out.println(c.chat("怎么退货？"));
//       c.ingest(java.util.List.of(PasmClient.item("退货政策", "7 天内无理由退货。", "faq")));
//       System.out.println(c.kbStats());
//   }
//
// 适用：Spring Boot / Vert.x / Android(API 26+ 可用 java.net.http，更低版本请换 OkHttp)
//
// 说明：为避免强制引入 Jackson/Gson，这里用一个极简的 JSON 字段提取器
//       （足以应付本网关的扁平响应）。若项目已有 JSON 库，替换 `Json.pick()` 即可。

package pasm;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 调用 pasm-framework 失败时抛出；status==0 表示网络层失败。 */
class PasmException extends RuntimeException {
    public final int status;
    public final String hint;

    public PasmException(String message, int status, String hint) {
        super(hint == null || hint.isEmpty()
                ? message + "（HTTP " + status + "）"
                : message + "（HTTP " + status + "）提示：" + hint);
        this.status = status;
        this.hint = hint == null ? "" : hint;
    }
}

/** 极简 JSON 工具：够用即可，不引入依赖。 */
final class Json {
    private Json() {}

    static String esc(String s) {
        if (s == null) return "";
        StringBuilder b = new StringBuilder(s.length() + 16);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':  b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n");  break;
                case '\r': b.append("\\r");  break;
                case '\t': b.append("\\t");  break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        return b.toString();
    }

    /** 取顶层字符串字段的值（找不到返回 null）。 */
    static String pick(String json, String field) {
        if (json == null) return null;
        String needle = "\"" + field + "\"";
        int i = json.indexOf(needle);
        if (i < 0) return null;
        int colon = json.indexOf(':', i + needle.length());
        if (colon < 0) return null;
        int p = colon + 1;
        while (p < json.length() && Character.isWhitespace(json.charAt(p))) p++;
        if (p >= json.length()) return null;
        if (json.charAt(p) == '"') {
            StringBuilder out = new StringBuilder();
            for (int k = p + 1; k < json.length(); k++) {
                char c = json.charAt(k);
                if (c == '\\') {
                    char n = json.charAt(++k);
                    switch (n) {
                        case 'n': out.append('\n'); break;
                        case 'r': out.append('\r'); break;
                        case 't': out.append('\t'); break;
                        case 'u':
                            out.append((char) Integer.parseInt(json.substring(k + 1, k + 5), 16));
                            k += 4;
                            break;
                        default: out.append(n);
                    }
                } else if (c == '"') {
                    return out.toString();
                } else {
                    out.append(c);
                }
            }
            return null;
        }
        // 数字 / true / false / null
        int end = p;
        while (end < json.length() && ",}\n\r ".indexOf(json.charAt(end)) < 0) end++;
        return json.substring(p, end).trim();
    }

    static int pickInt(String json, String field, int dflt) {
        String v = pick(json, field);
        try { return v == null ? dflt : Integer.parseInt(v.trim()); }
        catch (NumberFormatException e) { return dflt; }
    }
}

/** pasm-framework HTTP 网关客户端。 */
public class PasmClient implements AutoCloseable {

    private final String baseUrl;
    private final String token;
    private final HttpClient http;

    public PasmClient() { this("http://127.0.0.1:8080", null); }

    public PasmClient(String baseUrl, String token) {
        this.baseUrl = (baseUrl == null ? "http://127.0.0.1:8080" : baseUrl).replaceAll("/+$", "");
        this.token = token == null ? "" : token;
        this.http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
    }

    // ---- 底层 ----
    private String send(String method, String path, String body) {
        HttpRequest.Builder b = HttpRequest.newBuilder()
                .uri(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(30))
                .header("Accept", "application/json");
        if (!token.isEmpty()) b.header("Authorization", "Bearer " + token);
        if (body == null) {
            b.method(method, HttpRequest.BodyPublishers.noBody());
        } else {
            b.header("Content-Type", "application/json; charset=utf-8")
             .method(method, HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8));
        }
        HttpResponse<String> resp;
        try {
            resp = http.send(b.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (IOException | InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new PasmException("无法连接 pasm-framework 服务：" + e.getMessage(), 0,
                    "确认服务已启动、地址与端口正确");
        }
        int code = resp.statusCode();
        String text = resp.body();
        if (code < 200 || code >= 300) {
            String err = Json.pick(text, "error");
            String hint = Json.pick(text, "hint");
            throw new PasmException(err == null ? "请求失败" : err, code,
                    hint == null ? "" : hint);
        }
        return text;
    }

    // ---- 业务 ----
    /** 发一条消息，返回回复文本。 */
    public String chat(String text) { return chat(text, "default", null); }

    public String chat(String text, String sessionId, String userId) {
        Map<String, String> body = new LinkedHashMap<>();
        body.put("text", text);
        body.put("session_id", sessionId == null ? "default" : sessionId);
        if (userId != null) body.put("user_id", userId);
        return chatRaw(toJson(body));
    }

    private String chatRaw(String jsonBody) {
        String text = send("POST", "/api/chat", jsonBody);
        String reply = Json.pick(text, "reply");
        return reply == null ? "" : reply;
    }

    /** 构造一条摄取用资料项。 */
    public static Map<String, Object> item(String title, String content, String source) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("title", title);
        m.put("content", content);
        m.put("source", source == null ? "ingest" : source);
        m.put("tags", new ArrayList<String>());
        return m;
    }

    /** 批量写入资料库，返回新增条数。 */
    public int ingest(List<Map<String, Object>> items) {
        String resp = send("POST", "/api/ingest", "{\"items\":" + itemsToJson(items) + "}");
        return Json.pickInt(resp, "added", 0);
    }

    public boolean resetSession(String sessionId) {
        String resp = send("POST", "/api/sessions/reset",
                "{\"session_id\":\"" + Json.esc(sessionId) + "\"}");
        return "true".equals(Json.pick(resp, "ok"));
    }

    public String kbStats()  { return send("GET", "/api/kb/stats", null); }
    public String plugins()  { return send("GET", "/api/plugins", null); }
    public String summary()  { return send("GET", "/api/summary", null); }
    /** 健康检查（免鉴权）。 */
    public String health()   { return send("GET", "/healthz", null); }

    // ---- 认知能力（/api/cog/*，管理作用域）--------------------------------
    //
    // 这一组是给「要长记忆的业务系统」用的：把记忆、情绪、行为倾向接到自己的
    // 后端里，而不是只拿一句问答。
    //
    // 返回值一律是**原始 JSON 字符串** —— 认知响应是嵌套结构（hit 数组、
    // 权重表），本类自带的极简 `Json.pick()` 只够取顶层标量。项目里已有
    // Jackson/Gson 的，直接拿这个字符串反序列化成自己的 DTO 即可。
    //
    // 为什么要 GET 而不是全用 POST：只读操作（status/context/recall/semantic）
    // 用 GET 才能被浏览器/代理缓存与直接调试；写入操作一律 POST。
    //
    // ★ 全部需要**管理令牌**：认知接口能写记忆、改人格，比对话敏感得多。

    /** 能力探测：返回可用操作清单。用它做启动自检，别硬编码操作名。 */
    public String cogCapabilities() { return send("GET", "/api/cog/capabilities", null); }

    public String cogStatus(String agentId) {
        return send("GET", "/api/cog/status?" + agentIdQuery(agentId), null);
    }

    /** 取认知上下文（**只读，不写记忆**）：注入到大模型提示词用的一号接口。 */
    public String cogContext(String agentId, String query, int k) {
        return send("GET", "/api/cog/context?" + agentIdQuery(agentId)
                + "&k=" + k + "&query=" + urlenc(query), null);
    }

    public String cogRecall(String agentId, String query, int k) {
        return send("GET", "/api/cog/recall?" + agentIdQuery(agentId)
                + "&k=" + k + "&query=" + urlenc(query), null);
    }

    /** 语义检索，并解释每条**为什么**被召回（要能回答"你凭哪一条这么说的"）。 */
    public String cogSemantic(String agentId, String query, int k) {
        return send("GET", "/api/cog/semantic?" + agentIdQuery(agentId)
                + "&k=" + k + "&query=" + urlenc(query), null);
    }

    /** 写入一条记忆。salience 1–5，5 = 关键事实（不会被闲聊挤掉）。 */
    public String cogObserve(String agentId, String title, String brief,
                             List<String> tags, int salience) {
        StringBuilder b = new StringBuilder();
        b.append("{\"agent_id\":\"").append(Json.esc(agentId)).append("\",");
        b.append("\"title\":\"").append(Json.esc(title)).append("\",");
        b.append("\"brief\":\"").append(Json.esc(brief)).append("\",");
        b.append("\"salience\":").append(salience).append(",\"tags\":[");
        if (tags != null) {
            for (int i = 0; i < tags.size(); i++) {
                if (i > 0) b.append(',');
                b.append('"').append(Json.esc(tags.get(i))).append('"');
            }
        }
        b.append("]}");
        return send("POST", "/api/cog/observe", b.toString());
    }

    /** 报告带情绪效价的事件（valence ∈ [-1,1]）。 */
    public String cogFeel(String agentId, String event, double valence) {
        return send("POST", "/api/cog/feel", "{\"agent_id\":\"" + Json.esc(agentId)
                + "\",\"event\":\"" + Json.esc(event) + "\",\"valence\":" + valence + "}");
    }

    /** 反馈塑形。**务必带 action**，否则长期会让行为分布极端化。 */
    public String cogFeedback(String agentId, String kind, String action) {
        StringBuilder b = new StringBuilder();
        b.append("{\"agent_id\":\"").append(Json.esc(agentId)).append("\",");
        b.append("\"kind\":\"").append(Json.esc(kind)).append("\"");
        if (action != null && !action.isEmpty()) {
            b.append(",\"action\":\"").append(Json.esc(action)).append("\"");
        }
        return send("POST", "/api/cog/feedback", b.append('}').toString());
    }

    /** 按性格 + 学到的偏好选一个动作。 */
    public String cogAct(String agentId, List<String> candidates) {
        StringBuilder b = new StringBuilder();
        b.append("{\"agent_id\":\"").append(Json.esc(agentId)).append("\"");
        if (candidates != null && !candidates.isEmpty()) {
            b.append(",\"candidates\":[");
            for (int i = 0; i < candidates.size(); i++) {
                if (i > 0) b.append(',');
                b.append('"').append(Json.esc(candidates.get(i))).append('"');
            }
            b.append(']');
        }
        return send("POST", "/api/cog/act", b.append('}').toString());
    }

    /** 记忆巩固（睡眠回放）。apply=false 只给建议、不落盘 —— 建议默认取这个。 */
    public String cogConsolidate(String agentId, boolean apply) {
        return send("POST", "/api/cog/consolidate", "{\"agent_id\":\"" + Json.esc(agentId)
                + "\",\"apply\":" + apply + "}");
    }

    /** 查看人格。 */
    public String cogPersona(String agentId) {
        return send("GET", "/api/cog/persona?" + agentIdQuery(agentId), null);
    }

    /** 合并式更新人格（没传的键不会被抹掉）。 */
    public String cogSetPersona(String agentId, String personaJson) {
        return send("POST", "/api/cog/persona", "{\"agent_id\":\"" + Json.esc(agentId)
                + "\",\"persona\":" + personaJson + "}");
    }

    /** 落盘（agentId 传 null 则落盘全部已加载的 agent）。 */
    public String cogSave(String agentId) {
        String body = (agentId == null) ? "{}"
                : "{\"agent_id\":\"" + Json.esc(agentId) + "\"}";
        return send("POST", "/api/cog/save", body);
    }

    private static String agentIdQuery(String agentId) {
        return "agent_id=" + urlenc(agentId == null ? "default" : agentId);
    }

    /**
     * 百分号编码（UTF-8）。
     * ★ 必须做：查询串里会有中文（"青霉素"），不编码会直接被网关当成非法请求；
     *   而且 `&`/`=`/空格 不编码会**改变参数结构**（不是"少个字符"而已）。
     */
    static String urlenc(String s) {
        return java.net.URLEncoder.encode(s == null ? "" : s,
                java.nio.charset.StandardCharsets.UTF_8);
    }

    @Override public void close() { /* HttpClient 无需显式关闭（JDK 21+ 可 close） */ }

    // ---- JSON 组装 ----
    private static String toJson(Map<String, String> m) {
        StringBuilder b = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, String> e : m.entrySet()) {
            if (!first) b.append(',');
            first = false;
            b.append('"').append(Json.esc(e.getKey())).append("\":\"")
             .append(Json.esc(e.getValue())).append('"');
        }
        return b.append('}').toString();
    }

    private static String itemsToJson(List<Map<String, Object>> items) {
        StringBuilder b = new StringBuilder("[");
        boolean first = true;
        for (Map<String, Object> it : items) {
            if (!first) b.append(',');
            first = false;
            b.append('{');
            b.append("\"title\":\"").append(Json.esc(String.valueOf(it.get("title")))).append("\",");
            b.append("\"content\":\"").append(Json.esc(String.valueOf(it.get("content")))).append("\",");
            b.append("\"source\":\"").append(Json.esc(String.valueOf(it.getOrDefault("source", "ingest")))).append("\",");
            b.append("\"tags\":[");
            Object tags = it.get("tags");
            if (tags instanceof List) {
                boolean f2 = true;
                for (Object t : (List<?>) tags) {
                    if (!f2) b.append(',');
                    f2 = false;
                    b.append('"').append(Json.esc(String.valueOf(t))).append('"');
                }
            }
            b.append("]}");
        }
        return b.append(']').toString();
    }

    // ---- 手工冒烟 ----
    public static void main(String[] args) {
        String url = args.length > 0 ? args[0] : "http://127.0.0.1:8080";
        String tok = args.length > 1 ? args[1] : null;
        try (PasmClient c = new PasmClient(url, tok)) {
            System.out.println("health: " + Json.pick(c.health(), "status"));
            System.out.println("reply : " + c.chat("怎么退货？"));
            // 认知接口冒烟：拿不到就说明服务端 < 0.5.0 或认知层没装
            String caps = c.cogCapabilities();
            System.out.println("cog   : " + Json.pick(caps, "available")
                    + " ops=" + Json.pick(caps, "operations"));
            System.out.println("observe: " + Json.pick(
                    c.cogObserve("smoke", "冒烟记忆", "由 PasmClient.main 写入",
                            java.util.List.of("smoke"), 3), "ok"));
            System.out.println("recall : " + Json.pick(
                    c.cogRecall("smoke", "冒烟", 3), "count"));
        }
    }
}
