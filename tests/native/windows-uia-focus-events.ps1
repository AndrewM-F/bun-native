# Independent, bounded UI Automation focus-event observer for the hosted
# screen-reader fixture. It records only events from the window's process.
param(
  [Parameter(Mandatory = $true)][string]$Title,
  [Parameter(Mandatory = $true)][string]$Output,
  [Parameter(Mandatory = $true)][string]$Ready,
  [Parameter(Mandatory = $true)][string]$Stop
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0
try {
  Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, WindowsBase
  $references = @(
    [System.Windows.Automation.Automation].Assembly.Location,
    [System.Windows.Automation.AutomationElement].Assembly.Location,
    [System.Windows.Rect].Assembly.Location,
    'System.dll', 'System.Core.dll'
  ) | Select-Object -Unique
  Add-Type -ReferencedAssemblies $references -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Windows.Automation;

public static class BunNativeFocusEvents {
  private static readonly object Gate = new object();
  private static AutomationFocusChangedEventHandler handler;
  private static Stopwatch clock;
  private static string output;
  private static int pid, count, dropped, errors;
  private static string Encode(string value) {
    value = value ?? "";
    if (value.Length > 256) value = value.Substring(0, 256);
    return Convert.ToBase64String(Encoding.UTF8.GetBytes(value));
  }
  private static void Handle(object sender, AutomationFocusChangedEventArgs args) {
    lock (Gate) {
      try {
        var element = sender as AutomationElement;
        if (element == null || element.Current.ProcessId != pid) return;
        if (count >= 128) { dropped++; return; }
        var current = element.Current;
        count++;
        File.AppendAllText(output, String.Format(CultureInfo.InvariantCulture,
          "event\t{0}\t{1}\t{2}\t{3}\n", count, clock.ElapsedTicks,
          Encode(current.ControlType.ProgrammaticName), Encode(current.Name)), new UTF8Encoding(false));
      } catch { errors++; }
    }
  }
  public static void Start(int processId, string path) {
    pid = processId; output = path; clock = Stopwatch.StartNew();
    File.WriteAllText(output, "ticks_per_second\t" + Stopwatch.Frequency + "\n", new UTF8Encoding(false));
    handler = new AutomationFocusChangedEventHandler(Handle);
    Automation.AddAutomationFocusChangedEventHandler(handler);
  }
  public static void Stop() {
    if (handler == null) return;
    Automation.RemoveAutomationFocusChangedEventHandler(handler);
    lock (Gate) {
      File.AppendAllText(output, String.Format(CultureInfo.InvariantCulture,
        "end\t{0}\t{1}\t{2}\n", count, dropped, errors), new UTF8Encoding(false));
    }
  }
}
'@
  $automation = [System.Windows.Automation.AutomationElement]
  $condition = New-Object System.Windows.Automation.PropertyCondition($automation::NameProperty, $Title)
  $window = $automation::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $condition)
  if (-not $window) { throw 'UI Automation did not find the fixture window' }
  $processId = $window.Current.ProcessId
  if ($processId -le 0) { throw 'The fixture window has no process ID' }
  [BunNativeFocusEvents]::Start($processId, $Output)
  [System.IO.File]::WriteAllText($Ready, "$processId")
  $deadline = (Get-Date).AddMinutes(8)
  while (-not (Test-Path -LiteralPath $Stop)) {
    if ((Get-Date) -gt $deadline) { throw 'UI Automation focus observer timed out' }
    Start-Sleep -Milliseconds 100
  }
} catch {
  [System.IO.File]::WriteAllText("$Output.error", ($_ | Out-String))
  throw
} finally {
  if ('BunNativeFocusEvents' -as [type]) { [BunNativeFocusEvents]::Stop() }
}
