using System.Text.Json;
using HIDMaestro;

// Driver installation is explicitly excluded. Administrator installs it first
// using the upstream HIDMaestro instructions on their own Windows computer.
if (args.Length != 1 || args[0] is not ("xbox360" or "dualshock4")) return 2;
using var ctx = new HMContext();
ctx.LoadDefaultProfiles();
var profile = ctx.GetProfile(args[0] == "xbox360" ? "xbox-360-wired" : "dualshock-4-v2")
    ?? throw new InvalidOperationException("Required HIDMaestro controller profile not found");
using var controller = ctx.CreateController(profile);
var held = new HashSet<HMButton>();
var axes = new Dictionary<string, float>();
string[] names = ["left_x", "left_y", "right_x", "right_y", "left_trigger", "right_trigger"];
var map = new Dictionary<string, string> {
    ["a"]="A", ["b"]="B", ["x"]="X", ["y"]="Y",
    ["left_shoulder"]="LeftBumper", ["right_shoulder"]="RightBumper",
    ["back"]="Back", ["start"]="Start", ["left_thumb"]="LeftStick",
    ["right_thumb"]="RightStick"
};
var directions = new HashSet<string>();
void Submit() {
    HMButton buttons = default;
    foreach (var button in held) buttons |= button;
    // D-pad is an eight-way hat, not ordinary face buttons.
    var vertical = (directions.Contains("dpad_up") ? -1 : 0) +
                   (directions.Contains("dpad_down") ? 1 : 0);
    var horizontal = (directions.Contains("dpad_left") ? -1 : 0) +
                     (directions.Contains("dpad_right") ? 1 : 0);
    string hat = (vertical, horizontal) switch {
        (-1,0)=>"North",(-1,1)=>"NorthEast",(0,1)=>"East",
        (1,1)=>"SouthEast",(1,0)=>"South",(1,-1)=>"SouthWest",
        (0,-1)=>"West",(-1,-1)=>"NorthWest",_=>"Neutral"
    };
    var state = new HMGamepadState {
        Buttons = buttons,
        Axes = HMGamepadStateHelpers.StandardAxes(profile,
            leftStickX: (axes.GetValueOrDefault("left_x") + 1) / 2,
            leftStickY: (axes.GetValueOrDefault("left_y") + 1) / 2,
            rightStickX: (axes.GetValueOrDefault("right_x") + 1) / 2,
            rightStickY: (axes.GetValueOrDefault("right_y") + 1) / 2,
            leftTrigger: axes.GetValueOrDefault("left_trigger"),
            rightTrigger: axes.GetValueOrDefault("right_trigger"))
    };
    if (Enum.TryParse<HMHat>(hat, true, out var parsedHat)) state.Hat = parsedHat;
    controller.SubmitState(in state);
}
string? line;
while ((line = Console.ReadLine()) != null) {
    try {
        using var doc = JsonDocument.Parse(line);
        var root = doc.RootElement;
        var op = root.GetProperty("op").GetString();
        if (op == "reset") { held.Clear(); axes.Clear(); directions.Clear(); Submit(); }
        else if (op == "button") {
            var name = root.GetProperty("name").GetString() ?? "";
            bool down = root.GetProperty("down").GetBoolean();
            if (name.StartsWith("dpad_") && (name is "dpad_up" or "dpad_down" or "dpad_left" or "dpad_right")) {
                if (down) directions.Add(name); else directions.Remove(name);
                Submit();
            } else {
                if (!map.TryGetValue(name, out var mapped) || !Enum.TryParse<HMButton>(mapped, out var key))
                    throw new ArgumentException("Unsupported button");
                if (down) held.Add(key); else held.Remove(key);
                Submit();
            }
        } else if (op == "axis") {
            string name = root.GetProperty("name").GetString() ?? "";
            float val = root.GetProperty("value").GetSingle();
            if (!names.Contains(name) || !float.IsFinite(val) || val < -1 || val > 1)
                throw new ArgumentException("Invalid axis");
            axes[name] = name.EndsWith("trigger") ? Math.Clamp(val, 0, 1) : val;
            Submit();
        } else if (op != "ping") throw new ArgumentException("Unknown operation");
        Console.WriteLine("{\"ok\":true}");
    } catch (Exception ex) {
        Console.WriteLine(JsonSerializer.Serialize(new { ok = false, error = ex.Message }));
    }
}
held.Clear(); axes.Clear(); directions.Clear(); Submit();
