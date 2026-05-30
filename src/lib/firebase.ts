import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";
import { getAnalytics, logEvent } from "firebase/analytics";

const firebaseConfig = {
  apiKey: "AIzaSyDTM8WJ_e0XkE0vcBPQwD7QFUowoG2hE1E",
  authDomain: "fincoach-esat.firebaseapp.com",
  projectId: "fincoach-esat",
  storageBucket: "fincoach-esat.firebasestorage.app",
  messagingSenderId: "231143485349",
  appId: "1:231143485349:web:188cefb58abbbe4c99824c",
  measurementId: "G-85LEBV562D",
};

export const firebaseApp = initializeApp(firebaseConfig);
export const auth = getAuth(firebaseApp);
export const googleProvider = new GoogleAuthProvider();
export const analytics = getAnalytics(firebaseApp);
export { logEvent };
