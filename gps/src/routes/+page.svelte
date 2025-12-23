<script lang="ts">
    import { GpxTrackGenerator } from '$lib/gpxGenerator';
    import { NmeaParser } from '$lib/nmeaParser';
    import type { ConversionOptions, FilterOptions } from '$lib/interfaces';
    
    // --- STAV A PROMĚNNÉ POMOCÍ $state (Runes) ---

    // Vstupní NMEA data od uživatele
    let nmeaInput = $state<string>('');
    // Výsledný GPX XML
    let gpxOutput = $state<string>('');
    // Status pro zpětnou vazbu
    let status = $state<'idle' | 'processing' | 'success' | 'error'>('idle');
    let errorMessage = $state<string>('');

    // Konfigurace filtrů a konverze
    let gnssFilter = $state<'all' | 'gps' | 'glonass'>('all');
    let minTimeChangeMs = $state<number>(1); // 1.5 sekundy
    let minCourseChangeDeg = $state<number>();  // 5 stupňů
    let minDistanceChangeMeters = $state<number>(); // 2 metry

    // --- FUNKCE PRO ZPRACOVÁNÍ ---

    /**
     * Zpracuje NMEA vstup a vygeneruje GPX.
     */
    const processNmeaToGpx = () => {
        status = 'processing';
        errorMessage = '';
        gpxOutput = '';

        if (!nmeaInput.trim()) {
            status = 'error';
            errorMessage = 'Vstupní NMEA data nemohou být prázdná.';
            return;
        }

        try {
            const parser = new NmeaParser();
            const generator = new GpxTrackGenerator();

            const sentences = nmeaInput.trim().split('\n').map(s => s.trim()).filter(s => s.startsWith('$'));

            for (const sentence of sentences) {
                // Přes NmeaParser shromáždíme data do GpsDataPoint
                const point = parser.parse(sentence); 
                if (point) {
                    generator.addPoint(point);
                }
            }

            const filterOptions: FilterOptions = {
                minTimeChangeMs,
                minCourseChangeDeg,
                minDistanceChangeMeters,
            };

            const conversionOptions: ConversionOptions = {
                gnssFilter,
                filterOptions,
            };

            // Generování finálního GPX s aplikovanými filtry
            gpxOutput = generator.generateGpx(conversionOptions);
            status = 'success';

        } catch (e) {
            status = 'error';
            errorMessage = `Chyba při konverzi: ${e instanceof Error ? e.message : 'Neznámá chyba'}`;
            console.error(e);
        }
    };

    /**
     * Stáhne vygenerovaný GPX XML jako soubor.
     */
    const downloadGpx = () => {
        if (!gpxOutput) return;

        const blob = new Blob([gpxOutput], { type: 'application/gpx+xml' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `tracklog-${new Date().toISOString().slice(0, 10)}.gpx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    // --- COMPUTED VYUŽÍVAJÍCÍ $derived ---
    const isProcessing = $derived(status === 'processing');
</script>

<svelte:head>
	<title>GPS decoder</title>
	<meta name="description" content="GPS decoder and visualiser" />
</svelte:head>

<div class="min-h-screen bg-gray-50 p-6 font-sans">
    <header class="mb-8 text-center">
        <h1 class="text-4xl font-bold text-gray-800 flex items-center justify-center">
            🛰️ NMEA to GPX Konvertor
        </h1>
        <p class="text-gray-500">Převod NMEA dat s pokročilou filtrací do formátu GPX.</p>
    </header>

    <div class="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-8">
        <section class="lg:col-span-1 bg-white p-6 rounded-xl shadow-lg h-fit">
            <h2 class="text-2xl font-semibold text-gray-700 mb-4 border-b pb-2">⚙️ Konfigurace</h2>

            <div class="mb-5">
                <label for="gnssFilter" class="block text-sm font-medium text-gray-700 mb-1">GNSS Systém</label>
                <select id="gnssFilter" bind:value={gnssFilter} class="w-full p-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500  text-black">
                    <option value="all">Všechny (GPS/GLONASS/kombinované)</option>
                    <option value="gps">Pouze GPS</option>
                    <option value="glonass">Pouze GLONASS</option>
                </select>
            </div>

            <h3 class="text-lg font-medium text-gray-700 mb-3 mt-5">Podmínky pro Export Bodů:</h3>

            <div class="mb-4">
                <label for="minTime" class="block text-sm font-medium text-gray-700 mb-1">Min. změna času (ms)</label>
                <input 
                    type="number" 
                    id="minTime" 
                    bind:value={minTimeChangeMs} 
                    min="0" 
                    step="100" 
                    class="w-full p-2 border border-gray-300 rounded-md text-black"
                >
            </div>

            <div class="mb-4">
                <label for="minCourse" class="block text-sm font-medium text-gray-700 mb-1">Min. změna směru (stupně)</label>
                <input 
                    type="number" 
                    id="minCourse" 
                    bind:value={minCourseChangeDeg} 
                    min="0" 
                    max="180" 
                    class="w-full p-2 border border-gray-300 rounded-md  text-black"
                >
            </div>

            <div class="mb-4">
                <label for="minDistance" class="block text-sm font-medium text-gray-700 mb-1">Min. vzdálenost (metry)</label>
                <input 
                    type="number" 
                    id="minDistance" 
                    bind:value={minDistanceChangeMeters} 
                    min="0" 
                    step="0.5" 
                    class="w-full p-2 border border-gray-300 rounded-md text-black"
                >
            </div>

            <button 
                onclick={processNmeaToGpx} 
                disabled={isProcessing}
                class="w-full mt-6 py-3 px-4 rounded-lg text-white font-semibold transition-colors 
                       {isProcessing ? 'bg-blue-300 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'}">
                {isProcessing ? 'Zpracovávám...' : 'PŘEVÉST NMEA NA GPX'}
            </button>
        </section>

        <section class="lg:col-span-2">
            <div class="mb-6 bg-white p-6 rounded-xl shadow-lg">
                <h2 class="text-2xl font-semibold text-gray-700 mb-4 border-b pb-2">📥 NMEA Vstup</h2>
                <textarea 
                    bind:value={nmeaInput} 
                    rows="10" 
                    placeholder="Vložte NMEA věty sem, každá na nový řádek (např. $GPRMC, $GPGGA, ...)"
                    class="w-full p-3 border border-gray-300 rounded-md resize-none focus:ring-indigo-500 focus:border-indigo-500 font-mono text-sm text-black"
                ></textarea>
            </div>

            {#if status === 'error' && errorMessage}
                <div class="mb-6 p-3 bg-red-100 border border-red-400 text-red-700 rounded-md">
                    <p class="font-bold">Chyba!</p>
                    <p>{errorMessage}</p>
                </div>
            {:else if status === 'success'}
                <div class="mb-6 p-3 bg-green-100 border border-green-400 text-green-700 rounded-md">
                    <p class="font-bold">Hotovo!</p>
                    <p>GPX soubor byl úspěšně vygenerován.</p>
                </div>
            {/if}

            <div class="bg-white p-6 rounded-xl shadow-lg">
                <div class="flex justify-between items-center mb-4 border-b pb-2">
                    <h2 class="text-2xl font-semibold text-gray-700">📤 GPX Výstup</h2>
                    <button 
                        onclick={downloadGpx} 
                        disabled={!gpxOutput}
                        class="px-4 py-2 rounded-lg text-sm font-semibold transition-colors 
                               {gpxOutput ? 'bg-green-600 hover:bg-green-700 text-white' : 'bg-gray-300 text-gray-500 cursor-not-allowed'}">
                        Stáhnout GPX
                    </button>
                    <a 
                        href="https://gpx.studio/app" 
                        class="px-4 py-2 rounded-lg text-sm font-semibold transition-colors 
                               {gpxOutput ? 'bg-green-600 hover:bg-green-700 text-white' : 'bg-gray-300 text-gray-500 cursor-not-allowed'}">
                        Otevřít mapy
				</a>
                </div>
                
                <textarea 
                    bind:value={gpxOutput} 
                    rows="15" 
                    readonly 
                    placeholder="Vygenerovaný GPX XML se objeví zde..."
                    class="w-full p-3 border border-gray-300 rounded-md resize-none font-mono text-xs bg-gray-50 text-black"
                ></textarea>
            </div>
        </section>
    </div>
</div>