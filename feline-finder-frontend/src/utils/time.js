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