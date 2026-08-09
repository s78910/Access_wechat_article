-- AWA v2.1 SQLite 建表脚本
-- 目标数据库文件：data/sql/awa-v2.1.sqlite3
--
-- 设计原则：
-- 1. awa_public_accounts 只记录公众号本身。
-- 2. awa_public_articles 只记录文章索引和当前已保存的资源类型。
-- 3. awa_fetch_history 只记录联网获取资源的必要历史，不记录导出、删除、清理等本地操作。
--
-- 使用方式示例：
-- sqlite3 data/sql/awa-v2.1.sqlite3 < data/sql/create_script/create_awa_v2_1.sql

PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS awa_public_accounts (
    -- 本地公众号主键，供文章表和获取历史表关联。
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 公众号名称，例如“河北衡水中学”；同名公众号只保留一条索引。
    account_name TEXT NOT NULL UNIQUE
        CHECK (trim(account_name) <> ''),

    -- 首次记录该公众号的时间。
    created_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- 最近一次更新该公众号索引信息的时间。
    updated_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS awa_public_articles (
    -- 本地文章主键，供获取历史表关联。
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 所属公众号 ID。
    account_id INTEGER NOT NULL,

    -- 文章标题，按文章页面解析结果保存。
    article_title TEXT NOT NULL
        CHECK (trim(article_title) <> ''),

    -- 文章发布时间；按页面展示精度保存，例如 YYYY-MM-DD HH:MM。
    published_article_time TEXT NOT NULL DEFAULT '',

    -- 文章短链，用于同一公众号下的文章去重和后续重新打开。
    article_link TEXT NOT NULL
        CHECK (trim(article_link) <> ''),

    -- 本地归档目录；建议保存相对 storages/ 的路径，具体由程序统一解释。
    archive_dir TEXT NOT NULL DEFAULT '',

    -- 当前文章已保存的资源类型列表，例如：
    -- ["article_detail","origin_html","comment_detail","offline_html"]
    -- 这是快速索引；真实展示时仍以本地文件是否存在为准。
    resource_types_json TEXT NOT NULL DEFAULT '[]'
        CHECK (trim(resource_types_json) <> ''),

    -- 第一次成功采集该文章任一资源的时间。
    first_collected_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- 最近一次成功更新该文章资源的时间。
    last_collected_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- 文章索引记录创建时间。
    created_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- 文章索引记录更新时间。
    updated_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    FOREIGN KEY (account_id)
        REFERENCES awa_public_accounts(id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS awa_fetch_history (
    -- 联网资源获取历史主键。
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 关联文章 ID；如果任务失败时还没有形成文章索引，可以为空。
    article_id INTEGER,

    -- 关联公众号 ID；如果失败时还无法识别公众号，可以为空。
    account_id INTEGER,

    -- 本次任务目标公众号名称快照，方便失败记录也能展示。
    target_account_name TEXT NOT NULL DEFAULT '',

    -- 本次任务目标文章标题快照，失败时也保留用户看到的标题。
    target_title TEXT NOT NULL DEFAULT '',

    -- 本次任务目标链接或短链；未捕获到链接时允许为空。
    target_link TEXT NOT NULL DEFAULT '',

    -- 联网任务类型，例如 article_capture、comment_fetch、offline_cache。
    task_type TEXT NOT NULL
        CHECK (trim(task_type) <> ''),

    -- 本次任务目标或产出的资源类型列表，例如 ["article_detail","origin_html"]。
    resource_types_json TEXT NOT NULL DEFAULT '[]'
        CHECK (trim(resource_types_json) <> ''),

    -- 本次联网任务状态；只区分成功和失败。
    status TEXT NOT NULL
        CHECK (status IN ('success', 'failed')),

    -- 任务开始时间。
    started_time TEXT NOT NULL,

    -- 任务结束时间；异常中断时允许为空。
    finished_time TEXT NOT NULL DEFAULT '',

    -- 本次联网任务耗时，单位秒。
    duration_seconds REAL NOT NULL DEFAULT 0
        CHECK (duration_seconds >= 0),

    -- 失败阶段，例如 mitm_capture、reference_request、comment_fetch、offline_cache。
    error_stage TEXT NOT NULL DEFAULT '',

    -- 失败原因；成功时为空。
    error_message TEXT NOT NULL DEFAULT '',

    -- 本次任务成功产物目录；失败时允许为空。
    output_dir TEXT NOT NULL DEFAULT '',

    -- 历史记录创建时间。
    created_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    -- 历史记录更新时间；通常与创建时间一致，保留给未来异步状态更新使用。
    updated_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    FOREIGN KEY (article_id)
        REFERENCES awa_public_articles(id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    FOREIGN KEY (account_id)
        REFERENCES awa_public_accounts(id)
        ON UPDATE CASCADE
        ON DELETE SET NULL
);

-- 同一公众号下，同一短链只保留一篇文章索引。
CREATE UNIQUE INDEX IF NOT EXISTS ux_awa_public_articles_account_link
ON awa_public_articles(account_id, article_link);

CREATE INDEX IF NOT EXISTS idx_awa_public_articles_account_id
ON awa_public_articles(account_id);

CREATE INDEX IF NOT EXISTS idx_awa_public_articles_title
ON awa_public_articles(article_title);

CREATE INDEX IF NOT EXISTS idx_awa_public_articles_published_time
ON awa_public_articles(published_article_time);

CREATE INDEX IF NOT EXISTS idx_awa_public_articles_last_collected_time
ON awa_public_articles(last_collected_time);

CREATE INDEX IF NOT EXISTS idx_awa_fetch_history_article_id
ON awa_fetch_history(article_id);

CREATE INDEX IF NOT EXISTS idx_awa_fetch_history_account_id
ON awa_fetch_history(account_id);

CREATE INDEX IF NOT EXISTS idx_awa_fetch_history_task_type
ON awa_fetch_history(task_type);

CREATE INDEX IF NOT EXISTS idx_awa_fetch_history_status
ON awa_fetch_history(status);

CREATE INDEX IF NOT EXISTS idx_awa_fetch_history_started_time
ON awa_fetch_history(started_time);

CREATE INDEX IF NOT EXISTS idx_awa_fetch_history_target_title
ON awa_fetch_history(target_title);

COMMIT;
