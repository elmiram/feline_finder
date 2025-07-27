export const formatRelativeTime = (date) => {
    if (!date) return 'N/A';
    const now = new Date();
    const seconds = Math.round((now - new Date(date)) / 1000);
    const minutes = Math.round(seconds / 60);
    const hours = Math.round(minutes / 60);
    const days = Math.round(hours / 24);

    if (seconds < 60) return "just now";
    if (minutes < 60) return `${minutes} min ago`;
    if (hours < 24) return `${hours} hr ago`;
    return `${days} day(s) ago`;
};

export const formatDate = (date) => new Date(date).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
});

/**
 * Formats a timestamp to show the time if it's from today,
 * or the date and time if it's from a previous day.
 * @param {string} timestamp - The ISO string timestamp.
 * @returns {string} A formatted date/time string.
 */
export const formatEventTime = (timestamp) => {
    if (!timestamp) return '';
    const eventDate = new Date(timestamp);
    const now = new Date();

    const isToday = eventDate.getFullYear() === now.getFullYear() &&
        eventDate.getMonth() === now.getMonth() &&
        eventDate.getDate() === now.getDate();

    if (isToday) {
        // e.g., "10:17 pm"
        return eventDate.toLocaleTimeString(undefined, {
            hour: 'numeric',
            minute: '2-digit'
        }).toLowerCase();
    } else {
        // e.g., "jan 15 at 10:17 pm"
        return eventDate.toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit'
        }).replace(',', ' at').toLowerCase();
    }
};