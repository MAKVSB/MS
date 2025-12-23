package main

import (
	"fmt"
	"math/rand"
	"sync"
	"time"
)

// Item reprezentuje datovou položku.
type Item struct {
	ID        int
	Value     int
	UpdatedAt time.Time
}

// Server spravuje globální stav a notifikace.
type Server struct {
	items      map[int]*Item
	mu         sync.RWMutex
	subs       []chan []int // klientské kanály pro notifikace ID
	lastNotify time.Time    // čas posledního odeslání notifikace
}

// NewServer inicializuje server s daným počtem položek.
func NewServer(count int) *Server {
	s := &Server{
		items:      make(map[int]*Item),
		lastNotify: time.Now(),
	}
	for i := 0; i < count; i++ {
		s.items[i] = &Item{
			ID:        i,
			Value:     rand.Intn(100),
			UpdatedAt: time.Now(),
		}
	}
	return s
}

// Subscribe umožňuje klientovi přihlásit se k odběru notifikací o změnách ID.
func (s *Server) Subscribe() <-chan []int {
	ch := make(chan []int, 10)
	s.mu.Lock()
	s.subs = append(s.subs, ch)
	s.mu.Unlock()
	return ch
}

// GetItem umožňuje klientovi načíst aktuální hodnotu jedné položky podle ID.
// Vrací defenzivní kopii, aby klient nemohl přímo měnit stav serveru.
func (s *Server) GetItem(id int) (*Item, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	item, ok := s.items[id]
	if !ok {
		return nil, fmt.Errorf("položka s ID %d nenalezena", id)
	}

	// Vrácení kopie
	return &Item{
		ID:        item.ID,
		Value:     item.Value,
		UpdatedAt: item.UpdatedAt,
	}, nil
}

// getAllItems vrací kopii všech položek (pro počáteční synchronizaci).
func (s *Server) getAllItems() []*Item {
	s.mu.RLock()
	defer s.mu.RUnlock()

	data := make([]*Item, 0, len(s.items))
	for _, item := range s.items {
		// Vrácení kopie
		data = append(data, &Item{
			ID:        item.ID,
			Value:     item.Value,
			UpdatedAt: item.UpdatedAt,
		})
	}
	return data
}

// GetChangedItemIDsSince vrací seznam ID položek, které byly upraveny po daném čase 'since'.
// Tato metoda simuluje endpoint pro resynchronizaci.
// Klient odesílá svůj lastSyncTime, server mu vrátí ID položek, které se změnily po tomto čase.
func (s *Server) GetChangedItemIDsSince(since time.Time) []int {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var changed []int
	for id, item := range s.items {
		// Používáme After, abychom získali všechny položky, které se změnily
		// striktně po čase poslední synchronizace klienta.
		if item.UpdatedAt.After(since) {
			changed = append(changed, id)
		}
	}
	return changed
}

// náhodně edituje jednu položku
func (s *Server) randomEdit() {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Zajistíme, že máme alespoň jednu položku k editaci
	if len(s.items) == 0 {
		return
	}

	// Náhodný výběr ID
	var keys []int
	for id := range s.items {
		keys = append(keys, id)
	}
	id := keys[rand.Intn(len(keys))]

	item := s.items[id]
	item.Value = rand.Intn(1000)
	item.UpdatedAt = time.Now()
	fmt.Printf("Server: Upravil položku s ID: %v na novou hodnotu: %v\n", id, item.Value)
}

// najde položky, které se změnily od posledního notifikování
func (s *Server) getChangedItems() []int {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var changed []int
	for id, item := range s.items {
		if item.UpdatedAt.After(s.lastNotify) {
			changed = append(changed, id)
		}
	}
	return changed
}

// notifyClients odešle všem odběratelům seznam ID, která se změnila.
func (s *Server) notifyClients() {
	changed := s.getChangedItems()
	if len(changed) == 0 {
		return
	}

	// Odeslání notifikací klientům
	s.mu.RLock()
	// Vytvoříme kopii, abychom mohli uvolnit zámek dříve
	subsCopy := make([]chan []int, len(s.subs))
	copy(subsCopy, s.subs)
	s.mu.RUnlock()

	for _, ch := range subsCopy {
		select {
		case ch <- changed:
			// Notifikace odeslána
		default:
			// Kanál plný – ignoruj (aby se server nezasekl)
		}
	}

	// Aktualizujeme čas posledního oznámení (uvnitř samostatného zámku, protože se mění stav)
	s.mu.Lock()
	s.lastNotify = time.Now()
	s.mu.Unlock()
}

// Run spouští vlákna serveru pro úpravy a notifikace.
func (s *Server) Run() {
	// Vlákno pro náhodné úpravy dat
	go func() {
		for {
			s.randomEdit()
			time.Sleep(1000 * time.Millisecond) // Úprava každou 1 sekundu
		}
	}()

	// Vlákno pro notifikace (odesílá ID změn)
	go func() {
		for {
			s.notifyClients()
			time.Sleep(4 * time.Second) // Notifikace každé 4 sekundy
		}
	}()
}

// processUpdatesWithTimeout zpracovává notifikace po omezenou dobu.
func processUpdatesWithTimeout(id int, s *Server, cache map[int]*Item, updates <-chan []int) {
	// Klient 1 bude zpracovávat updaty jen na omezenou dobu, aby simuloval odpojení.
	// Připojen 5 až 12 sekund
	timeout := time.After(time.Duration(rand.Intn(8)+5) * time.Second)

	for {
		select {
		case changedIDs, ok := <-updates:
			if !ok {
				fmt.Printf("Klient %d: Kanál notifikací byl zavřen.\n", id)
				return
			}

			fmt.Printf("Klient %d: Obdržel notifikaci o změnách ID: %v. Načítám nová data...\n", id, changedIDs)

			// Logika pro stažení dat
			for _, itemID := range changedIDs {
				fetchedItem, err := s.GetItem(itemID)
				if err != nil {
					fmt.Printf("Klient %d: Chyba při načítání ID %d: %v\n", id, itemID, err)
					continue
				}

				// Aktualizace lokální cache
				cache[itemID] = fetchedItem
				fmt.Printf("Klient %d: Úspěšně aktualizoval položku ID %d. Nová hodnota: %d. (Server čas: %s)\n",
					id, fetchedItem.ID, fetchedItem.Value, fetchedItem.UpdatedAt.Format("15:04:05"))
			}

		case <-timeout:
			// Čas vypršel, návrat do hlavní smyčky klienta pro odpojení
			return
		}
	}
}

// processUpdates zpracovává notifikace dokud kanál není uzavřen.
func processUpdates(id int, s *Server, cache map[int]*Item, updates <-chan []int) {
	for changedIDs := range updates {
		fmt.Printf("Klient %d: Obdržel notifikaci o změnách ID: %v. Načítám nová data...\n", id, changedIDs)

		for _, itemID := range changedIDs {
			fetchedItem, err := s.GetItem(itemID)
			if err != nil {
				fmt.Printf("Klient %d: Chyba při načítání ID %d: %v\n", id, itemID, err)
				continue
			}

			cache[itemID] = fetchedItem
			fmt.Printf("Klient %d: Úspěšně aktualizoval položku ID %d. Nová hodnota: %d. (Server čas: %s)\n",
				id, fetchedItem.ID, fetchedItem.Value, fetchedItem.UpdatedAt.Format("15:04:05"))
		}
	}
}

// client simuluje klienta, který udržuje lokální cache a připojuje se/odpojuje.
func client(id int, s *Server) {
	// Lokální cache klienta
	cache := make(map[int]*Item)
	// Čas poslední úspěšné synchronizace dat
	lastSyncTime := time.Time{}

	// Spouštěcí smyčka klienta
	for {
		// --- Fáze 1: Resynchronizace/Počáteční připojení ---
		var itemsToProcess []*Item

		if lastSyncTime.IsZero() {
			// První připojení: Načíst všechna data
			itemsToProcess = s.getAllItems()

		} else {
			// Zpětné připojení: Získat ID změn od posledního synchronizovaného času
			// Klient posílá serveru svůj čas poslední synchronizace
			changedIDs := s.GetChangedItemIDsSince(lastSyncTime)
			fmt.Printf("Klient %d: Znovu připojení (poslední synchronizace: %s). Dotazuji server na změny. Server hlásí %d ID ke stažení: %v\n",
				id, lastSyncTime.Format("15:04:05"), len(changedIDs), changedIDs)

			// Načíst změněné položky
			for _, itemID := range changedIDs {
				fetchedItem, err := s.GetItem(itemID)
				if err != nil {
					fmt.Printf("Klient %d: Chyba při načítání ID %d: %v\n", id, itemID, err)
					continue
				}
				itemsToProcess = append(itemsToProcess, fetchedItem)
			}
		}

		// Aktualizace lokální cache a lastSyncTime na základě právě stažených dat
		currentMaxTime := lastSyncTime
		for _, item := range itemsToProcess {
			cache[item.ID] = item // Aktualizace/vložení do cache
			if item.UpdatedAt.After(currentMaxTime) {
				currentMaxTime = item.UpdatedAt // Najít nejnovější čas ze stažených dat
			}
		}

		// Aktualizace lastSyncTime, pokud jsme něco stáhli
		if !currentMaxTime.Equal(lastSyncTime) || lastSyncTime.IsZero() {
			lastSyncTime = currentMaxTime
		}

		// Zajistit, aby se lastSyncTime inicializoval, i když nic nebylo staženo při prvním připojení
		if lastSyncTime.IsZero() {
			lastSyncTime = time.Now()
		}

		fmt.Printf("Klient %d: Hotovo synchronizace. Velikost cache: %d. Nová LastSyncTime: %s\n",
			id, len(cache), lastSyncTime.Format("15:04:05"))

		// --- Fáze 2: Přihlášení k odběru a zpracování notifikací ---
		updatesChan := s.Subscribe()

		if id == 1 {
			// Klient 1: Zůstane připojen jen po dobu timeoutu
			processUpdatesWithTimeout(id, s, cache, updatesChan)

			// Odpojení
			fmt.Printf("Klient %d: *** ODPOJENÍ *** (simulace pádu/odchodu)\n", id)
			disconnectTime := time.Duration(rand.Intn(5)+2) * time.Second // 2 až 6 sekund
			time.Sleep(disconnectTime)
			fmt.Printf("Klient %d: *** ZNOVU PŘIPOJENÍ po %v ***\n", id, disconnectTime)

			// Smyčka for {} se postará o přechod na Fázi 1 (Resynchronizace/Počáteční připojení)

		} else {
			// Klienti 0 a 2: Zůstanou připojeni
			processUpdates(id, s, cache, updatesChan)
			// Tato smyčka je nekonečná, Klienti 0 a 2 se nikdy neodpojí (pokud server nezavře kanál)
			break
		}
	}
}

func main() {
	server := NewServer(10)
	server.Run()

	// vytvoříme několik klientů
	for i := 0; i < 2; i++ {
		// Klient nyní přijímá referenci na server a stará se o počáteční i re-synchronizaci
		go client(i, server)
	}

	select {} // blokuje hlavní vlákno
}
