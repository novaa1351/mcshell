package dev.mcshell.net;

import java.util.List;

/**
 * One sample of what the machine is doing.
 *
 * <p>Arrives once a second while the task-manager tab is open and never
 * otherwise — the daemon does not sample when nobody is looking, because a
 * sample costs it about 23ms.
 *
 * <p>Already sorted and already cut to the number of rows asked for. Sorting
 * happens in the daemon on purpose: a machine has hundreds of processes and a
 * screen has room for tens, so sorting here would mean sending all of them
 * every second in order to draw a fraction of them.
 */
public record ProcessState(float cpu, List<Float> cores, long memUsed, long memTotal,
		long swapUsed, long swapTotal, List<Float> load, int count, List<Row> procs) {

	public static final ProcessState EMPTY =
			new ProcessState(0, List.of(), 0, 0, 0, 0, List.of(), 0, List.of());

	/**
	 * One process.
	 *
	 * @param cpu       share of the whole machine, not of one core, so the
	 *                  column sums to the gauge above it
	 * @param protectedProcess one of the things the shell is standing on. The
	 *                  kill button greys out; the daemon refuses regardless,
	 *                  because a client is not to be trusted with that
	 */
	public record Row(int pid, String name, String cmd, String user,
			float cpu, float mem, long rss, boolean protectedProcess) {
	}
}
