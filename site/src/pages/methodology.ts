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
          <li><strong>Pünktlich</strong> — weniger als 1 Minute Abweichung</li>
          <li><strong>Verspätet (+N min)</strong> — tatsächliche Ankunft N Minuten nach Fahrplan</li>
          <li><strong>Ausgefallen</strong> — Zug wurde von der DB als ausgefallen gemeldet</li>
        </ul>
      </dd>

      <dt>Werden alle Züge erfasst?</dt>
      <dd>Es werden nur Züge der Linie <strong>S7</strong> am Bahnhof Baierbrunn
          berücksichtigt.</dd>

      <dt>Warum fehlen manchmal Daten?</dt>
      <dd>Kurzfristige Ausfälle des Abrufservers oder der DB-API können zu
          Lücken führen. Die Daten spiegeln daher nicht zwingend alle Züge wider.</dd>
    </dl>
  `;
}
