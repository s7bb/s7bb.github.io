export function renderMethodology(container: HTMLElement): void {
  container.innerHTML = `
    <h2>Methodik</h2>
    <dl class="faq">
      <dt>Woher kommen die Daten?</dt>
      <dd>Von der offiziellen <strong>DB Timetables API</strong> der Deutschen Bahn
          (DB API Marketplace). Diese API liefert Soll- und Ist-Zeiten sowie
          Ausfallinformationen für alle Bahnhöfe.</dd>

      <dt>Wie oft wird aktualisiert?</dt>
      <dd>Die Daten werden alle <strong>5 Minuten</strong> abgerufen und stündlich
          auf dieser Seite veröffentlicht.</dd>

      <dt>Was bedeuten die Statusangaben?</dt>
      <dd>
        <ul>
          <li><strong>Pünktlich</strong> - weniger als 1 Minute Abweichung</li>
          <li><strong>Verspätet (+N min)</strong> - tatsächliche Ankunft N Minuten nach Fahrplan</li>
          <li><strong>Ausgefallen</strong> - Zug wurde von der DB als ausgefallen gemeldet</li>
        </ul>
      </dd>

      <dt>Was bedeutet „keine Daten"?</dt>
      <dd>Für diesen planmäßigen Zug (20-Minuten-Takt) liegen keine Informationen
          aus der DB-API vor. Das kann bedeuten:
        <ul>
          <li>Der Abruf war zum Zeitpunkt des Zuges ausgefallen</li>
          <li>Die DB-API hat diesen Zug nicht zurückgeliefert</li>
        </ul>
        Ein Zug ohne Daten ist <em>nicht</em> dasselbe wie ein ausgefallener Zug -
        er erscheint hier nur als Lücke im 20-Minuten-Raster.</dd>

      <dt>Werden alle Züge erfasst?</dt>
      <dd>Es werden nur Züge der Linie <strong>S7</strong> am Bahnhof Baierbrunn
          in beiden Richtungen erfasst: Richtung München und Richtung Wolfratshausen.</dd>

      <dt>Warum fehlen manchmal Daten?</dt>
      <dd>Kurzfristige Ausfälle des Abrufservers oder der DB-API können zu
          Lücken führen. Die Daten spiegeln daher nicht zwingend alle Züge wider.</dd>

      <dt>Datenquelle &amp; Lizenz</dt>
      <dd>Datenquelle:
          <a href="https://developers.deutschebahn.com/db-api-marketplace/apis/product/timetables"
             target="_blank" rel="noopener">DB Timetables API</a>
          der Deutschen Bahn (DB Station&amp;Service AG / DB InfraGO AG),
          lizenziert unter
          <a href="https://creativecommons.org/licenses/by/4.0/"
             target="_blank" rel="noopener">CC BY 4.0</a>.
          Die Daten werden aufbereitet und aggregiert
          (Verspätungs- und Pünktlichkeitsauswertung). Die Deutsche Bahn
          übernimmt keine Gewähr für Vollständigkeit oder Richtigkeit der
          Daten.</dd>
    </dl>
  `;
}
