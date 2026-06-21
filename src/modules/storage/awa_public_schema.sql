-- AWA 公众号与文章本地存储表结构。
-- 为避免采集到异常长文本时入库失败，文本字段不设置长度限制。

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS awa_public_accounts (
    -- 本地公众号主键，用于被文章表引用。
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 公众号名称：必须是非空文本；未知公众号这类业务占位值由代码层拦截。
    account_name TEXT NOT NULL UNIQUE
        CHECK (trim(account_name) <> ''),

    -- 首次记录该公众号的时间，SQLite 推荐用 ISO 时间字符串保存。
    created_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- 最近一次采集到该公众号文章的时间。
    updated_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS awa_public_articles (
    -- 本地文章记录主键。
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 关联 awa_public_accounts.id。
    account_id INTEGER NOT NULL,

    -- 文章标题：必须是非空文本；未识别标题这类业务占位值由代码层拦截。
    article_title TEXT NOT NULL
        CHECK (trim(article_title) <> ''),

    -- 文章发布时间；成功时按页面展示精度保存到分钟级：YYYY-MM-DD HH:MM，失败或超时时允许置空。
    published_article_time TEXT DEFAULT '',

    -- 文章短链接：成功时必须保存采集到的短链接；失败或超时时直接置空，不再写 failed:// 占位符。
    article_link TEXT DEFAULT '',

    -- 本次实际采集内容类型，例如：文章详情、评论信息、文章详情, 评论信息。
    record_type TEXT NOT NULL
        CHECK (trim(record_type) <> ''),

    -- 本次采集时间。
    collect_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- 采集耗时，单位秒；从模拟点击主页标题区域开始，到本地存储结束。
    duration_seconds REAL NOT NULL DEFAULT 0
        CHECK (duration_seconds >= 0),

    -- 下载状态：当前只允许 saved / failed，后续有新状态再扩展 CHECK。
    collect_status TEXT NOT NULL
        CHECK (collect_status IN ('saved', 'failed')),

    -- 只有成功保存的记录要求具备短链接；失败或超时记录的 article_link 可以为空。
    CHECK (collect_status <> 'saved' OR trim(coalesce(article_link, '')) <> ''),

    FOREIGN KEY (account_id)
        REFERENCES awa_public_accounts(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

-- 旧版本按 account_id + article_link 全量唯一；失败记录 article_link 允许置空后必须移除该限制。
DROP INDEX IF EXISTS ux_awa_public_articles_account_link;

-- 成功记录仍按同一公众号下的文章短链接去重；失败/超时空链接不参与这个唯一约束。
CREATE UNIQUE INDEX IF NOT EXISTS ux_awa_public_articles_saved_account_link
ON awa_public_articles(account_id, article_link)
WHERE collect_status = 'saved' AND trim(coalesce(article_link, '')) <> '';

-- 失败记录按公众号 + 标题 + 采集类型合并，方便后续同标题同公众号失败后重试更新。
CREATE UNIQUE INDEX IF NOT EXISTS ux_awa_public_articles_failed_account_title_type
ON awa_public_articles(account_id, article_title, record_type)
WHERE collect_status = 'failed';

CREATE INDEX IF NOT EXISTS idx_awa_public_articles_account_title_status
ON awa_public_articles(account_id, article_title, collect_status);

CREATE INDEX IF NOT EXISTS idx_awa_public_articles_account_id
ON awa_public_articles(account_id);

CREATE INDEX IF NOT EXISTS idx_awa_public_articles_collect_time
ON awa_public_articles(collect_time);

CREATE INDEX IF NOT EXISTS idx_awa_public_articles_collect_status
ON awa_public_articles(collect_status);

COMMIT;
