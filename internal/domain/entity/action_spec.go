// Package entity defines core domain entities for TetraCore Hub.
package entity

// ActionSpec визначає специфікацію дії (action) для валідації задач.
// Кожна дія має перелік обов'язкових та дозволених параметрів.
type ActionSpec struct {
	// Name — унікальна назва дії.
	Name string `json:"name"`
	// Required — обов'язкові параметри (ключ = назва, значення = true).
	Required map[string]bool `json:"required"`
	// Allowed — дозволені параметри (whitelist, ключ = назва, значення = true).
	Allowed map[string]bool `json:"allowed"`
	// MaxAttempts — максимальна кількість спроб виконання (за замовчуванням 3).
	MaxAttempts int `json:"max_attempts"`
}

// ActionSpecRegistry — реєстр специфікацій дій.
// Забезпечує пошук та реєстрацію ActionSpec за назвою.
type ActionSpecRegistry struct {
	specs map[string]*ActionSpec
}

// NewActionSpecRegistry створює порожній реєстр специфікацій.
func NewActionSpecRegistry() *ActionSpecRegistry {
	return &ActionSpecRegistry{
		specs: make(map[string]*ActionSpec),
	}
}

// Register додає специфікацію дії до реєстру.
// Якщо MaxAttempts не задано — встановлюється за замовчуванням 3.
func (r *ActionSpecRegistry) Register(spec *ActionSpec) {
	if spec == nil {
		return
	}
	if spec.MaxAttempts <= 0 {
		spec.MaxAttempts = 3
	}
	if spec.Required == nil {
		spec.Required = make(map[string]bool)
	}
	if spec.Allowed == nil {
		spec.Allowed = make(map[string]bool)
	}

	// Базові дозволені поля, що присутні в усіх специфікаціях
	spec.Allowed["earliest_run_time"] = true
	spec.Allowed["task_type"] = true

	r.specs[spec.Name] = spec
}

// Get повертає специфікацію за назвою дії.
// Другий аргумент — true, якщо знайдено.
func (r *ActionSpecRegistry) Get(action string) (*ActionSpec, bool) {
	spec, ok := r.specs[action]
	return spec, ok
}

// Has перевіряє, чи є специфікація для даної дії.
func (r *ActionSpecRegistry) Has(action string) bool {
	_, ok := r.specs[action]
	return ok
}

// DefaultActionSpecRegistry повертає реєстр зі всіма вбудованими специфікаціями дій.
// Відповідає ACTION_SPECS з Python TaskManager.
func DefaultActionSpecRegistry() *ActionSpecRegistry {
	registry := NewActionSpecRegistry()

	// test_simple: тестова дія
	registry.Register(&ActionSpec{
		Name:        "test_simple",
		Required:    map[string]bool{},
		Allowed:     map[string]bool{"message": true, "timestamp": true},
		MaxAttempts: 3,
	})

	// set_group_active_status: встановлення статусу активності групи
	registry.Register(&ActionSpec{
		Name:        "set_group_active_status",
		Required:    map[string]bool{"chat_id": true, "is_active": true},
		Allowed:     map[string]bool{"is_active": true},
		MaxAttempts: 3,
	})

	// remove_inactive_chats: видалення неактивних чатів
	registry.Register(&ActionSpec{
		Name:        "remove_inactive_chats",
		Required:    map[string]bool{},
		Allowed:     map[string]bool{},
		MaxAttempts: 5,
	})

	// check_subscriptions: перевірка підписок
	registry.Register(&ActionSpec{
		Name:        "check_subscriptions",
		Required:    map[string]bool{},
		Allowed:     map[string]bool{},
		MaxAttempts: 5,
	})

	// cleanup_inactive_modules: очищення неактивних модулів
	registry.Register(&ActionSpec{
		Name:        "cleanup_inactive_modules",
		Required:    map[string]bool{},
		Allowed:     map[string]bool{},
		MaxAttempts: 3,
	})

	// cleanup_cache: очищення кешу
	registry.Register(&ActionSpec{
		Name:        "cleanup_cache",
		Required:    map[string]bool{},
		Allowed:     map[string]bool{},
		MaxAttempts: 10,
	})

	// get_chat_settings: отримання налаштувань чату
	registry.Register(&ActionSpec{
		Name:        "get_chat_settings",
		Required:    map[string]bool{"chat_id": true},
		Allowed:     map[string]bool{},
		MaxAttempts: 3,
	})

	// create_group_settings: створення налаштувань групи
	registry.Register(&ActionSpec{
		Name: "create_group_settings",
		Required: map[string]bool{
			"chat_id": true,
		},
		Allowed: map[string]bool{
			"title":        true,
			"language":     true,
			"subscription": true,
			"is_forum":     true,
			"is_active":    true,
			"chat_type":    true,
		},
		MaxAttempts: 3,
	})

	// set_group_status: встановлення статусу групи
	registry.Register(&ActionSpec{
		Name: "set_group_status",
		Required: map[string]bool{
			"chat_id":   true,
			"is_active": true,
		},
		Allowed:     map[string]bool{"is_active": true},
		MaxAttempts: 3,
	})

	return registry
}
