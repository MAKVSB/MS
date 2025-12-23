// src/lib/utils.ts

/**
 * Převede NMEA souřadnici (DDMM.MMMM) a směr (N/S/E/W) na desetinné stupně (DDD.DDDDDD).
 * @param nmeaValue Hodnota ve formátu DDMM.MMMM (např. '4949.459645')
 * @param direction Směr N, S, E, W
 * @returns Desetinné stupně, nebo null pokud je neplatné.
 */
export function convertNmeaCoordToDecimal(
  nmeaValue: string,
  direction: string
): number | undefined {
  if (!nmeaValue || nmeaValue.length < 3) return;

  try {
    // Najdi, kde začínají minuty (za celými stupni)
    const pointIndex = nmeaValue.indexOf(".");
    if (pointIndex === -1) return;

    // Vypočti, kde končí celá čísla stupňů (DD nebo DDD)
    const degreesStr = nmeaValue.substring(0, pointIndex - 2);
    const minutesStr = nmeaValue.substring(pointIndex - 2);

    const degrees = parseFloat(degreesStr);
    const minutes = parseFloat(minutesStr);

    if (isNaN(degrees) || isNaN(minutes)) return;

    // Přepočet: Stupně + (Minuty / 60)
    let decimal = degrees + minutes / 60;

    // Aplikace znaménka
    const dirUpper = direction.toUpperCase();
    if (dirUpper === "S" || dirUpper === "W") {
      decimal = -decimal;
    }

    return decimal;
  } catch (e) {
    console.error("Chyba konverze souřadnic:", e);
    return;
  }
}

/**
 * Převede NMEA čas (HHMMSS.SS) a datum (DDMMYY) na Date objekt.
 * Datum je často pouze z RMC věty.
 * @param timeStr Čas UTC (HHMMSS.SS)
 * @param dateStr Datum (DDMMYY)
 * @returns Platný Date objekt, nebo null.
 */
export function createDateFromNmea(
  timeStr: string | null,
  dateStr: string | null
): Date | undefined {
  if (!timeStr || !dateStr || timeStr.length < 6 || dateStr.length !== 6) {
    return;
  }

  try {
    const DD = parseInt(dateStr.substring(0, 2), 10);
    const MM = parseInt(dateStr.substring(2, 4), 10) - 1; // Měsíce 0-11
    const YY = parseInt(dateStr.substring(4, 6), 10);

    // Předpokládáme aktuální století (2000+) - standardní chování
    const YYYY = YY > 80 ? 1900 + YY : 2000 + YY;

    const HH = parseInt(timeStr.substring(0, 2), 10);
    const MI = parseInt(timeStr.substring(2, 4), 10);
    const SS = parseFloat(timeStr.substring(4));

    const date = new Date(
      Date.UTC(
        YYYY,
        MM,
        DD,
        HH,
        MI,
        Math.floor(SS),
        Math.round((SS % 1) * 1000)
      )
    );

    if (isNaN(date.getTime())) {
      return;
    }
    return date;
  } catch (e) {
    return;
  }
}

/**
 * Převede řetězec na číslo, vrátí null pokud je prázdný nebo neplatný.
 */
export function parseNumber(value: string | undefined): number | undefined {
  if (value === undefined || value.trim() === "") return;
  const num = parseFloat(value);
  return isNaN(num) ? undefined : num;
}
