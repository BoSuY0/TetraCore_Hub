// Package redis provides Redis client infrastructure for TetraCore Hub.
package redis

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	goredis "github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
)

// Lua-скрипти для атомарних операцій з розподіленими блокуваннями.
// Відповідають Lua-скриптам Python TaskManager.
var (
	// luaAcquire — скрипт для захоплення блокування.
	// KEYS[1] = lock key, ARGV[1] = owner value, ARGV[2] = TTL в мілісекундах.
	// SET key value NX PX ttl_ms
	luaAcquire = goredis.NewScript(`
		if redis.call("SET", KEYS[1], ARGV[1], "NX", "PX", ARGV[2]) then
			return 1
		else
			return 0
		end
	`)

	// luaRelease — скрипт для звільнення блокування.
	// Перевіряє, що блокування належить поточному власнику (за префіксом owner).
	// KEYS[1] = lock key, ARGV[1] = owner prefix.
	luaRelease = goredis.NewScript(`
		local val = redis.call("GET", KEYS[1])
		if val == false then
			return 0
		end
		if string.sub(val, 1, string.len(ARGV[1])) == ARGV[1] then
			redis.call("DEL", KEYS[1])
			return 1
		else
			return 0
		end
	`)

	// luaExtend — скрипт для продовження TTL блокування.
	// Перевіряє, що блокування належить поточному власнику.
	// KEYS[1] = lock key, ARGV[1] = owner prefix, ARGV[2] = new TTL в мілісекундах.
	luaExtend = goredis.NewScript(`
		local val = redis.call("GET", KEYS[1])
		if val == false then
			return 0
		end
		if string.sub(val, 1, string.len(ARGV[1])) == ARGV[1] then
			redis.call("PEXPIRE", KEYS[1], ARGV[2])
			return 1
		else
			return 0
		end
	`)
)

// DistributedLock — розподілене блокування на базі Redis.
// Забезпечує взаємне виключення між конкурентними процесами.
type DistributedLock struct {
	rdb    goredis.Scripter
	key    string
	owner  string
	ttl    time.Duration
	logger zerolog.Logger
}

// NewDistributedLock створює нове розподілене блокування.
//
// Параметри:
//   - rdb: клієнт Redis (використовує Scripter для Lua-скриптів)
//   - key: ключ блокування в Redis
//   - owner: ідентифікатор власника (префікс для перевірки)
//   - ttl: час життя блокування
//   - logger: логер
func NewDistributedLock(rdb goredis.Scripter, key, owner string, ttl time.Duration, logger zerolog.Logger) *DistributedLock {
	if ttl <= 0 {
		ttl = 30 * time.Second
	}

	return &DistributedLock{
		rdb:    rdb,
		key:    key,
		owner:  owner,
		ttl:    ttl,
		logger: logger.With().Str("component", "distributed-lock").Str("lock_key", key).Logger(),
	}
}

// Acquire намагається захопити блокування.
// Повертає true, якщо блокування успішно захоплено.
// Значення блокування = "owner:timestamp" для ідентифікації.
func (l *DistributedLock) Acquire(ctx context.Context) (bool, error) {
	lockValue := fmt.Sprintf("%s:%d", l.owner, time.Now().UnixMilli())
	ttlMs := l.ttl.Milliseconds()

	result, err := luaAcquire.Run(ctx, l.rdb, []string{l.key}, lockValue, ttlMs).Int64()
	if err != nil {
		l.logger.Error().Err(err).
			Str("owner", l.owner).
			Msg("Помилка захоплення блокування")
		return false, fmt.Errorf("помилка захоплення блокування: %w", err)
	}

	acquired := result == 1

	if acquired {
		l.logger.Debug().
			Str("owner", l.owner).
			Dur("ttl", l.ttl).
			Msg("Блокування захоплено")
	} else {
		l.logger.Debug().
			Str("owner", l.owner).
			Msg("Блокування зайнято іншим власником")
	}

	return acquired, nil
}

// Release звільняє блокування (тільки якщо належить поточному власнику).
// Повертає true, якщо блокування успішно звільнено.
func (l *DistributedLock) Release(ctx context.Context) (bool, error) {
	result, err := luaRelease.Run(ctx, l.rdb, []string{l.key}, l.owner).Int64()
	if err != nil {
		l.logger.Error().Err(err).
			Str("owner", l.owner).
			Msg("Помилка звільнення блокування")
		return false, fmt.Errorf("помилка звільнення блокування: %w", err)
	}

	released := result == 1

	if released {
		l.logger.Debug().
			Str("owner", l.owner).
			Msg("Блокування звільнено")
	} else {
		l.logger.Warn().
			Str("owner", l.owner).
			Msg("Не вдалося звільнити блокування (не належить або вже звільнено)")
	}

	return released, nil
}

// Extend продовжує TTL блокування (тільки якщо належить поточному власнику).
// Повертає true, якщо TTL успішно продовжено.
func (l *DistributedLock) Extend(ctx context.Context, newTTL time.Duration) (bool, error) {
	if newTTL <= 0 {
		newTTL = l.ttl
	}

	ttlMs := newTTL.Milliseconds()

	result, err := luaExtend.Run(ctx, l.rdb, []string{l.key}, l.owner, ttlMs).Int64()
	if err != nil {
		l.logger.Error().Err(err).
			Str("owner", l.owner).
			Dur("new_ttl", newTTL).
			Msg("Помилка продовження блокування")
		return false, fmt.Errorf("помилка продовження блокування: %w", err)
	}

	extended := result == 1

	if extended {
		l.logger.Debug().
			Str("owner", l.owner).
			Dur("new_ttl", newTTL).
			Msg("TTL блокування продовжено")
	} else {
		l.logger.Warn().
			Str("owner", l.owner).
			Msg("Не вдалося продовжити блокування (не належить або вже звільнено)")
	}

	return extended, nil
}

// AcquireLock — допоміжна функція для створення та захоплення блокування.
// Генерує унікальний owner ID та повертає блокування, статус захоплення та помилку.
func AcquireLock(ctx context.Context, rdb goredis.Scripter, key string, ttl time.Duration, logger zerolog.Logger) (*DistributedLock, bool, error) {
	owner := uuid.New().String()
	lock := NewDistributedLock(rdb, key, owner, ttl, logger)

	acquired, err := lock.Acquire(ctx)
	if err != nil {
		return nil, false, err
	}

	return lock, acquired, nil
}
