<?php
/**
 * pasm-framework PHP 客户端（依赖 cURL 扩展，PHP 7.4+）。
 *
 * 用法：
 *   require __DIR__ . '/PasmClient.php';
 *
 *   $c = new PasmClient('http://127.0.0.1:8080', 'your-secret');
 *   echo $c->chat('怎么退货？', 'user-1');
 *   $c->ingest([['title' => '退货政策', 'content' => '7 天内无理由退货。', 'source' => 'faq']]);
 *   print_r($c->kbStats());
 *
 * 适用：Laravel / ThinkPHP / WordPress 插件 / 传统 PHP 站点客服接口。
 */

class PasmException extends Exception
{
    /** @var int HTTP 状态码（0 表示网络层失败） */
    public $status;

    /** @var string 服务端给的修复建议 */
    public $hint;

    public function __construct(string $message, int $status = 0, string $hint = '')
    {
        $this->status = $status;
        $this->hint = $hint;
        parent::__construct(
            $hint !== '' ? sprintf('%s（HTTP %d）提示：%s', $message, $status, $hint)
                         : sprintf('%s（HTTP %d）', $message, $status)
        );
    }
}

class PasmClient
{
    private string $baseUrl;
    private string $token;
    private int $timeout;

    public function __construct(string $baseUrl = 'http://127.0.0.1:8080',
                                ?string $token = null, int $timeout = 30)
    {
        $this->baseUrl = rtrim($baseUrl, '/');
        $this->token = $token ?? '';
        $this->timeout = $timeout;
    }

    /**
     * 底层请求。
     *
     * @param array<string,mixed>|null $payload
     * @return array<string,mixed>
     * @throws PasmException
     */
    private function request(string $method, string $path, ?array $payload = null): array
    {
        $ch = curl_init($this->baseUrl . $path);
        $headers = ['Accept: application/json'];
        $opts = [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CUSTOMREQUEST  => $method,
            CURLOPT_TIMEOUT        => $this->timeout,
            CURLOPT_CONNECTTIMEOUT => 10,
        ];
        if ($payload !== null) {
            $opts[CURLOPT_POSTFIELDS] = json_encode($payload, JSON_UNESCAPED_UNICODE);
            $headers[] = 'Content-Type: application/json; charset=utf-8';
        }
        if ($this->token !== '') {
            $headers[] = 'Authorization: Bearer ' . $this->token;
        }
        $opts[CURLOPT_HTTPHEADER] = $headers;
        curl_setopt_array($ch, $opts);

        $body = curl_exec($ch);
        if ($body === false) {
            $err = curl_error($ch);
            curl_close($ch);
            throw new PasmException('无法连接 pasm-framework 服务：' . $err, 0,
                '确认服务已启动、地址与端口正确');
        }
        $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        $obj = json_decode((string) $body, true);
        if (!is_array($obj)) {
            $obj = ['error' => mb_substr((string) $body, 0, 200)];
        }
        if ($code < 200 || $code >= 300) {
            throw new PasmException($obj['error'] ?? '请求失败', $code, $obj['hint'] ?? '');
        }
        return $obj;
    }

    /** 发一条消息，返回回复文本。 */
    public function chat(string $text, string $sessionId = 'default',
                         ?string $userId = null, ?array $meta = null): string
    {
        $payload = ['text' => $text, 'session_id' => $sessionId];
        if ($userId !== null) { $payload['user_id'] = $userId; }
        if ($meta !== null)   { $payload['meta'] = $meta; }
        return (string) ($this->request('POST', '/api/chat', $payload)['reply'] ?? '');
    }

    /**
     * 批量写入资料库，返回新增条数（需服务端启用 knowledge_base）。
     *
     * @param array<int,array<string,mixed>> $items
     */
    public function ingest(array $items): int
    {
        $r = $this->request('POST', '/api/ingest', ['items' => $items]);
        return (int) ($r['added'] ?? 0);
    }

    public function resetSession(string $sessionId): bool
    {
        $r = $this->request('POST', '/api/sessions/reset', ['session_id' => $sessionId]);
        return (bool) ($r['ok'] ?? false);
    }

    public function kbStats(): array { return $this->request('GET', '/api/kb/stats'); }
    public function plugins(): array { return $this->request('GET', '/api/plugins'); }
    public function summary(): array { return $this->request('GET', '/api/summary'); }

    /** 健康检查（免鉴权）。 */
    public function health(): array  { return $this->request('GET', '/healthz'); }
}

// ---- 命令行冒烟：php PasmClient.php [url] [token] ----
if (PHP_SAPI === 'cli' && isset($argv[0]) && realpath($argv[0]) === realpath(__FILE__)) {
    $c = new PasmClient($argv[1] ?? 'http://127.0.0.1:8080', $argv[2] ?? null);
    echo 'health: ' . ($c->health()['status'] ?? '?') . PHP_EOL;
    echo 'reply : ' . $c->chat('怎么退货？') . PHP_EOL;
}
