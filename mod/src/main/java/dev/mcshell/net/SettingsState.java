package dev.mcshell.net;

import java.util.List;

/**
 * One settings page, exactly as the daemon described it.
 *
 * <p>Like {@link CatalogState} this crosses from the socket thread to the
 * render thread, so it must never be mutated after construction.
 *
 * <p>The mod does not know what any of these rows <em>mean</em>. It knows how
 * to draw a slider, a toggle and a cycling button, and it knows to send the key
 * back with a new value. That is the whole of M6's promise: a new setting is a
 * change to the daemon, and this file never hears about it.
 */
public record SettingsState(String page, List<Row> rows) {
	public static final SettingsState EMPTY = new SettingsState("", List.of());

	/** What kind of control a row wants. Unknown types are drawn as text. */
	public enum Type {
		FLOAT, INT, BOOL, ENUM, KEYBIND, ACTION, TEXT, LABEL;

		static Type of(String name) {
			for (Type t : values()) {
				if (t.name().equalsIgnoreCase(name)) {
					return t;
				}
			}
			return LABEL;
		}
	}

	/** One choice in an ENUM row. {@code id} is opaque and goes back verbatim. */
	public record Option(String id, String label) {
	}

	/**
	 * One row.
	 *
	 * <p>The three value fields are a flat union: which one is meaningful is
	 * decided by {@link #type}. A sealed hierarchy would be tidier and would
	 * cost a visitor at every use site, for three cases that never grow.
	 *
	 * @param number  FLOAT and INT
	 * @param flag    BOOL
	 * @param choice  ENUM — the id of the selected option; KEYBIND — the key
	 *                combination as it should be drawn, already prettified;
	 *                TEXT — what is in the field
	 * @param defaultChoice what Reset restores, or null when the row has no
	 *                default and so no Reset button
	 * @param unit    "%" means draw the 0..1 value as a percentage
	 * @param detail  secondary line, or empty
	 * @param enabled false draws greyed and refuses input
	 * @param placeholder TEXT — what an empty field says it wants
	 * @param extraLabel a button at the right-hand end of the row, or empty
	 * @param extraKey   what that button sets to true. The screen does not know
	 *                what it means; it is an {@code action} row that happens to
	 *                share a line with something else
	 */
	public record Row(String key, Type type, String label, String group, String detail,
			double number, boolean flag, String choice, String defaultChoice,
			double min, double max, double step, String unit,
			List<Option> options, boolean enabled,
			String placeholder, String extraLabel, String extraKey) {

		/** Where this row's value sits between min and max, as 0..1. */
		public double normalised() {
			double span = max - min;
			if (span <= 0) {
				return 0;
			}
			return Math.clamp((number - min) / span, 0.0, 1.0);
		}

		/** The value a slider at {@code fraction} of its track stands for. */
		public double denormalised(double fraction) {
			double raw = min + fraction * (max - min);
			if (step > 0) {
				raw = Math.round(raw / step) * step;
			}
			return Math.clamp(raw, min, max);
		}

		/** How the value should read to a person: "57%", "0.5", "1920". */
		public String display() {
			if ("%".equals(unit)) {
				return Math.round(number * 100) + "%";
			}
			if (type == Type.INT) {
				return String.valueOf(Math.round(number));
			}
			String text = String.valueOf(Math.round(number * 100) / 100.0);
			return unit.isEmpty() ? text : text + " " + unit;
		}

		/** The label of the selected option, falling back to its raw id. */
		public String choiceLabel() {
			for (Option option : options) {
				if (option.id().equals(choice)) {
					return option.label();
				}
			}
			return choice == null ? "" : choice;
		}

		/** Whether this row is already at the value Reset would give it. */
		public boolean isDefault() {
			return defaultChoice == null || defaultChoice.equals(choice);
		}

		public boolean hasDefault() {
			return defaultChoice != null;
		}

		public boolean hasExtra() {
			return extraKey != null && !extraKey.isEmpty();
		}

		/** The field's contents, or the empty string. Never null. */
		public String text() {
			return choice == null ? "" : choice;
		}

		public int indexOfChoice() {
			for (int i = 0; i < options.size(); i++) {
				if (options.get(i).id().equals(choice)) {
					return i;
				}
			}
			return -1;
		}
	}

	/** The rows of one group, in the order the daemon sent them. */
	public List<Row> inGroup(String group) {
		return rows.stream().filter(r -> r.group().equals(group)).toList();
	}

	/** Group names, in first-appearance order. Empty string is the unnamed group. */
	public List<String> groups() {
		return rows.stream().map(Row::group).distinct().toList();
	}
}
