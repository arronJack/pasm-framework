// Package pasm 是 pasm-framework HTTP 网关的 Go 客户端（零第三方依赖）。
//
// 用法：
//
//	c := pasm.NewClient("http://127.0.0.1:8080", "your-secret")
//	reply, err := c.Chat("怎么退货？", "user-1")
//	added, err := c.Ingest([]pasm.IngestItem{
//	    {Title: "退货政策", Content: "7 天内无理由退货。", Source: "faq"},
//	})
//	health, err := c.Health()
//
// 适用：Gin/Echo 后端、边缘网关、内部运维工具。
package pasm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Error 是统一的调用错误；Status 为 0 表示网络层失败。
type Error struct {
	Message string
	Status  int
	Hint    string
}

func (e *Error) Error() string {
	if e.Hint != "" {
		return fmt.Sprintf("%s（HTTP %d）提示：%s", e.Message, e.Status, e.Hint)
	}
	return fmt.Sprintf("%s（HTTP %d）", e.Message, e.Status)
}

// Client 是 pasm-framework 网关客户端。
type Client struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

// NewClient 创建客户端。token 为空表示服务端未开启鉴权。
func NewClient(baseURL, token string) *Client {
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		Token:   token,
		HTTP:    &http.Client{Timeout: 30 * time.Second},
	}
}

// ChatRequest / ChatResponse 对应 POST /api/chat
type ChatRequest struct {
	Text      string         `json:"text"`
	SessionID string         `json:"session_id,omitempty"`
	UserID    string         `json:"user_id,omitempty"`
	Meta      map[string]any `json:"meta,omitempty"`
}

type ChatResponse struct {
	Reply     string `json:"reply"`
	SessionID string `json:"session_id"`
}

// IngestItem / IngestResponse 对应 POST /api/ingest
type IngestItem struct {
	Title   string   `json:"title"`
	Content string   `json:"content"`
	Source  string   `json:"source,omitempty"`
	Tags    []string `json:"tags,omitempty"`
}

type IngestResponse struct {
	Added   int  `json:"added"`
	Total   int  `json:"total"`
	Docs    int  `json:"docs"`
	QA      int  `json:"qa"`
	Enabled bool `json:"enabled"`
}

// Health 对应 GET /healthz
type Health struct {
	Status       string         `json:"status"`
	Listening    bool           `json:"listening"`
	Host         string         `json:"host"`
	Port         int            `json:"port"`
	AuthRequired bool           `json:"auth_required"`
	Metrics      map[string]any `json:"metrics,omitempty"`
}

// KBStats 对应 GET /api/kb/stats
type KBStats struct {
	Total   int  `json:"total"`
	Docs    int  `json:"docs"`
	QA      int  `json:"qa"`
	Enabled bool `json:"enabled"`
}

func (c *Client) do(ctx context.Context, method, path string, payload any, out any) error {
	var body io.Reader
	if payload != nil {
		raw, err := json.Marshal(payload)
		if err != nil {
			return &Error{Message: "请求体序列化失败：" + err.Error()}
		}
		body = bytes.NewReader(raw)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, body)
	if err != nil {
		return &Error{Message: "构造请求失败：" + err.Error()}
	}
	req.Header.Set("Accept", "application/json")
	if payload != nil {
		req.Header.Set("Content-Type", "application/json; charset=utf-8")
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return &Error{Message: "无法连接 pasm-framework 服务：" + err.Error(),
			Hint: "确认服务已启动、地址与端口正确"}
	}
	defer resp.Body.Close()

	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		var e struct {
			Error string `json:"error"`
			Hint  string `json:"hint"`
		}
		_ = json.Unmarshal(raw, &e)
		if e.Error == "" {
			e.Error = "请求失败"
		}
		return &Error{Message: e.Error, Status: resp.StatusCode, Hint: e.Hint}
	}
	if out == nil || len(raw) == 0 {
		return nil
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return &Error{Message: "响应解析失败：" + err.Error(), Status: resp.StatusCode}
	}
	return nil
}

// Chat 发一条消息，返回回复文本。
func (c *Client) Chat(text, sessionID string) (string, error) {
	if sessionID == "" {
		sessionID = "default"
	}
	var out ChatResponse
	err := c.do(context.Background(), http.MethodPost, "/api/chat",
		ChatRequest{Text: text, SessionID: sessionID}, &out)
	return out.Reply, err
}

// ChatContext 带 context 的版本（推荐在 HTTP 服务里使用）。
func (c *Client) ChatContext(ctx context.Context, text, sessionID, userID string) (string, error) {
	if sessionID == "" {
		sessionID = "default"
	}
	var out ChatResponse
	err := c.do(ctx, http.MethodPost, "/api/chat",
		ChatRequest{Text: text, SessionID: sessionID, UserID: userID}, &out)
	return out.Reply, err
}

// Ingest 批量写入资料库，返回新增条数（需服务端启用 knowledge_base）。
func (c *Client) Ingest(items []IngestItem) (int, error) {
	for i := range items {
		if items[i].Source == "" {
			items[i].Source = "ingest"
		}
	}
	var out IngestResponse
	err := c.do(context.Background(), http.MethodPost, "/api/ingest",
		map[string]any{"items": items}, &out)
	return out.Added, err
}

// ResetSession 清空某个会话的历史。
func (c *Client) ResetSession(sessionID string) (bool, error) {
	var out struct {
		OK bool `json:"ok"`
	}
	err := c.do(context.Background(), http.MethodPost, "/api/sessions/reset",
		map[string]string{"session_id": sessionID}, &out)
	return out.OK, err
}

// KBStats 资料库统计。
func (c *Client) KBStats() (*KBStats, error) {
	var out KBStats
	err := c.do(context.Background(), http.MethodGet, "/api/kb/stats", nil, &out)
	return &out, err
}

// Plugins 插件清单与启用状态（原始 map，避免为易变结构建类型）。
func (c *Client) Plugins() (map[string]any, error) {
	var out map[string]any
	err := c.do(context.Background(), http.MethodGet, "/api/plugins", nil, &out)
	return out, err
}

// Summary 应用快照。
func (c *Client) Summary() (map[string]any, error) {
	var out map[string]any
	err := c.do(context.Background(), http.MethodGet, "/api/summary", nil, &out)
	return out, err
}

// Health 健康检查（免鉴权）。
func (c *Client) Health() (*Health, error) {
	var out Health
	err := c.do(context.Background(), http.MethodGet, "/healthz", nil, &out)
	return &out, err
}
