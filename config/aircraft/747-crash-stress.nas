# GPL-2.0-or-later. Adapter for the unmodified JA37 CrashAndStress 0.19.
# Contact indices are verified against names by the overlay installer.
var crashCode = nil;
var lastImpact = -10;
# Ground starts have no approach initialiser; approach starts must finish
# relocation before arming. Both require real FDM and scenery readiness.
var ready = func {
    var approach = getprop('/sim/committee/approach-ready');
    return getprop('/sim/signals/fdm-initialized') and
        getprop('/sim/sceneryloaded') and (approach == nil or approach == 1);
};

# Upstream does not guard its water loop during pause/replay/reset. Guard all
# paths here, and wait for the approach initialiser to finish relocating.
CrashAndStress._isRunning = func {
    return me.inService and !me.repairing and
        !getprop('/sim/replay/replay-state') and
        !getprop('/sim/freeze/master') and
        !getprop('/sim/freeze/clock') and
        ready() and
        me.fdm.input.simTime.getValue() > 1;
};
var upstreamLoop = CrashAndStress._loop;
CrashAndStress._loop = func {
    if (me._isRunning()) call(upstreamLoop, [], me);
};
var upstreamImpact = CrashAndStress._impactDamage;
CrashAndStress._impactDamage = func {
    if (!me._isRunning()) return;
    var now = me.fdm.input.simTime.getValue();
    # Several contact points can hit in one impact. Do not roll the failure
    # dice repeatedly or restart the sound on each contact callback.
    if (now - lastImpact < 1) return;
    lastImpact = now;
    call(upstreamImpact, [], me);
};
CrashAndStress._startImpactListeners = func {
    foreach (var contact; me.wowStructure) {
        setlistener(contact, func(n) {
            if (n.getBoolValue()) me._impactDamage();
        }, 0, 0);
    }
};

var actuator = func(path) {
    return {
        parents: [FailureMgr.FailureActuator],
        set_failure_level: func(level) { setprop(path, level > 0); },
        get_failure_level: func { return getprop(path) ? 1 : 0; }
    };
};

var clear = func {
    lastImpact = -10;
    if (crashCode == nil) return;
    crashCode.stop();
    foreach (var timer; [crashCode.repairTimer, crashCode.soundWaterTimer,
                        crashCode.soundTimer, crashCode.explodeTimer,
                        crashCode.stressTimer]) timer.stop();
    FailureMgr.repair_all();
    crashCode._initProperties();
    crashCode.wingsAttached = 1;
    crashCode.exploded = 0;
    crashCode.repairing = 0;
    crashCode.lastMessageTime = -10;
    setprop('/sim/crashed', 0);
};

var nativeRepair = Boeing747.repair;
Boeing747.repair = func {
    clear();
    nativeRepair();
    if (crashCode != nil) crashCode.start();
};
setlistener('/sim/signals/reinit', func { clear(); });

setlistener('/sim/signals/frame', func {
    if (!ready()) return;
    if (crashCode == nil) {
        # Reuse the native wing-break switch and fuel cutoffs; no invented
        # asymmetric aerodynamics, collapsed gear, flames or damaged meshes.
        FailureMgr.add_failure_mode('committee/wings', '747 wing failure',
            actuator('/controls/failures/wings/broken'));
        for (var i = 0; i < 4; i += 1) {
            FailureMgr.add_failure_mode('committee/engine-' ~ i, '747 engine ' ~ (i+1),
                actuator('/controls/engines/engine[' ~ i ~ ']/cutoff'));
        }
        # Experimental stress scale anchored to this flight's initial weight
        # and the aircraft's existing 5 g cutoff, not Boeing damage data.
        crashCode = CrashAndStress.new([0,1,2,3,4],
            {weightLbs: getprop('/fdm/jsbsim/inertia/weight-lbs'), maxG: 5},
            ['committee/wings']);
        # Native 5 g failure can precede the weight-scaled upstream threshold.
        setlistener('/controls/failures/wings/broken', func(n) {
            if (n.getBoolValue() and crashCode._isRunning() and crashCode.wingsAttached)
                crashCode._stressDamage('excessive');
        }, 0, 0);
        setprop('/sim/committee/crash-stress-ready', 1);
        print('747 crash-and-stress ready: five gear and seven structural contacts.');
    }
    crashCode.start();
});
