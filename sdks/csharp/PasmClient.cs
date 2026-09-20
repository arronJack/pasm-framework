// pasm-framework C# / .NET 客户端（零第三方依赖，用 BCL 的 System.Net.Http + System.Text.Json）
//
// 用法：
//   using Pasm;
//
//   var c = new PasmClient("http://127.0.0.1:8080", "your-secret");
//   Console.WriteLine(await c.ChatAsync("怎么退货？", sessionId: "user-1"));
//   await c.IngestAsync(new[] { new IngestItem { Title = "退货政策",
//                                                Content = "7 天内无理由退货。",
//                                                Source = "faq" } });
//   Console.WriteLine(string.Join(",", (await c.HealthAsync()).Keys));
//
// 适用：WPF / WinForms / WinUI / MAUI / ASP.NET Core / Unity(非 IL2CPP 限制场景)。

using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace Pasm
{
    /// <summary>调用 pasm-framework 失败时抛出。Status 为 0 表示网络层失败。</summary>
    public class PasmException : Exception
    {
        public int Status { get; }
        public string Hint { get; }

        public PasmException(string message, int status = 0, string hint = "")
            : base(hint.Length > 0 ? $"{message}（HTTP {status}）提示：{hint}" : $"{message}（HTTP {status}）")
        {
            Status = status;
            Hint = hint;
        }
    }

    public class ChatRequest
    {
        [JsonPropertyName("text")] public string Text { get; set; } = "";
        [JsonPropertyName("session_id")] public string SessionId { get; set; } = "default";
        [JsonPropertyName("user_id")] public string? UserId { get; set; }
        [JsonPropertyName("meta")] public Dictionary<string, object>? Meta { get; set; }
    }

    public class ChatResponse
    {
        [JsonPropertyName("reply")] public string Reply { get; set; } = "";
        [JsonPropertyName("session_id")] public string SessionId { get; set; } = "";
    }

    public class IngestItem
    {
        [JsonPropertyName("title")] public string Title { get; set; } = "";
        [JsonPropertyName("content")] public string Content { get; set; } = "";
        [JsonPropertyName("source")] public string Source { get; set; } = "ingest";
        [JsonPropertyName("tags")] public List<string> Tags { get; set; } = new List<string>();
    }

    public class IngestRequest
    {
        [JsonPropertyName("items")] public List<IngestItem> Items { get; set; } = new List<IngestItem>();
    }

    public class IngestResponse
    {
        [JsonPropertyName("added")] public int Added { get; set; }
        [JsonPropertyName("total")] public int Total { get; set; }
        [JsonPropertyName("docs")] public int Docs { get; set; }
        [JsonPropertyName("qa")] public int Qa { get; set; }
        [JsonPropertyName("enabled")] public bool Enabled { get; set; }
    }

    /// <summary>pasm-framework HTTP 网关客户端。</summary>
    public class PasmClient : IDisposable
    {
        private static readonly JsonSerializerOptions JsonOpts = new JsonSerializerOptions
        {
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        };

        private readonly HttpClient _http;

        public string BaseUrl { get; }
        public string Token { get; }

        public PasmClient(string baseUrl = "http://127.0.0.1:8080", string? token = null,
                          TimeSpan? timeout = null)
        {
            BaseUrl = (baseUrl ?? "").TrimEnd('/');
            Token = token ?? "";
            _http = new HttpClient { Timeout = timeout ?? TimeSpan.FromSeconds(30) };
        }

        private HttpRequestMessage Build(HttpMethod method, string path, object? body = null)
        {
            var req = new HttpRequestMessage(method, BaseUrl + path);
            if (!string.IsNullOrEmpty(Token))
                req.Headers.TryAddWithoutValidation("Authorization", "Bearer " + Token);
            if (body != null)
                req.Content = JsonContent.Create(body, options: JsonOpts);
            return req;
        }

        private async Task<JsonElement> SendAsync(HttpMethod method, string path,
                                                  object? body = null,
                                                  CancellationToken ct = default)
        {
            HttpResponseMessage resp;
            try
            {
                resp = await _http.SendAsync(Build(method, path, body), ct).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                throw new PasmException($"无法连接 pasm-framework 服务：{ex.Message}", 0,
                                        "确认服务已启动、地址与端口正确");
            }

            var text = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
            JsonElement root = default;
            try
            {
                if (!string.IsNullOrWhiteSpace(text))
                    root = JsonDocument.Parse(text).RootElement.Clone();
            }
            catch { /* 非 JSON，交给下面按状态码处理 */ }

            if (!resp.IsSuccessStatusCode)
            {
                string err = "请求失败", hint = "";
                if (root.ValueKind == JsonValueKind.Object)
                {
                    if (root.TryGetProperty("error", out var e)) err = e.GetString() ?? err;
                    if (root.TryGetProperty("hint", out var h)) hint = h.GetString() ?? "";
                }
                throw new PasmException(err, (int)resp.StatusCode, hint);
            }
            return root;
        }

        /// <summary>发一条消息，返回回复文本。</summary>
        public async Task<string> ChatAsync(string text, string sessionId = "default",
                                            string? userId = null,
                                            Dictionary<string, object>? meta = null,
                                            CancellationToken ct = default)
        {
            var body = new ChatRequest { Text = text, SessionId = sessionId, UserId = userId, Meta = meta };
            var root = await SendAsync(HttpMethod.Post, "/api/chat", body, ct).ConfigureAwait(false);
            return root.TryGetProperty("reply", out var r) ? (r.GetString() ?? "") : "";
        }

        /// <summary>批量写入资料库，返回新增条数（需服务端启用 knowledge_base）。</summary>
        public async Task<int> IngestAsync(IEnumerable<IngestItem> items,
                                           CancellationToken ct = default)
        {
            var body = new IngestRequest { Items = new List<IngestItem>(items) };
            var root = await SendAsync(HttpMethod.Post, "/api/ingest", body, ct).ConfigureAwait(false);
            return root.TryGetProperty("added", out var a) ? a.GetInt32() : 0;
        }

        public async Task<bool> ResetSessionAsync(string sessionId, CancellationToken ct = default)
        {
            var root = await SendAsync(HttpMethod.Post, "/api/sessions/reset",
                new Dictionary<string, string> { ["session_id"] = sessionId }, ct)
                .ConfigureAwait(false);
            return root.ValueKind == JsonValueKind.Object
                   && root.TryGetProperty("ok", out var ok) && ok.GetBoolean();
        }

        public Task<JsonElement> KbStatsAsync(CancellationToken ct = default)
            => SendAsync(HttpMethod.Get, "/api/kb/stats", null, ct);

        public Task<JsonElement> PluginsAsync(CancellationToken ct = default)
            => SendAsync(HttpMethod.Get, "/api/plugins", null, ct);

        public Task<JsonElement> SummaryAsync(CancellationToken ct = default)
            => SendAsync(HttpMethod.Get, "/api/summary", null, ct);

        /// <summary>健康检查（免鉴权）。</summary>
        public Task<JsonElement> HealthAsync(CancellationToken ct = default)
            => SendAsync(HttpMethod.Get, "/healthz", null, ct);

        public void Dispose() => _http.Dispose();
    }
}
