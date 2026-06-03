// Placeholder root page. The real dashboard is still served by dashboard-v2.
// Phase 9 will migrate routes one-by-one to Next.js. The subscription page
// (/subscribe/) is the first migrated route.
export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center px-6">
      <div className="text-center max-w-md">
        <div className="text-3xl font-bold tracking-tight">NexusPanel</div>
        <p className="mt-3 text-text-dim">
          صفحه‌ی اشتراک کاربر را از طریق لینک <span dir="ltr" className="font-mono">/sub/&lt;token&gt;/</span> باز کنید.
        </p>
      </div>
    </main>
  );
}
